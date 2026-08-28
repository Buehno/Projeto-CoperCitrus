"""Camada de automacao RPA baseada em Playwright e Chromium."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .errors import BrowserBlockedError, ConfigurationError, ProviderError
from .settings import Settings


BLOCK_MARKERS = (
    "acesso negado",
    "access denied",
    "captcha",
    "checking your browser",
    "nossos sistemas detectaram trafego incomum",
    "robot check",
    "unusual traffic",
    "verify you are human",
    "verifique se voce e humano",
)
MANUAL_VERIFICATION_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class SiteSelectors:
    cards: tuple[str, ...]
    titles: tuple[str, ...]
    prices: tuple[str, ...]
    links: tuple[str, ...]
    descriptions: tuple[str, ...] = ()
    sellers: tuple[str, ...] = ()
    images: tuple[str, ...] = ("img",)


@dataclass(frozen=True, slots=True)
class BrowserProductCard:
    title: str
    price_text: str | None
    purchase_url: str
    description: str | None = None
    seller: str | None = None
    image_url: str | None = None
    raw_text: str | None = None


class BrowserRpa:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._connected_over_cdp = False

    def __enter__(self) -> BrowserRpa:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(self) -> None:
        if self._context is not None:
            return
        try:
            self._playwright = sync_playwright().start()
            launch_options: dict[str, Any] = {
                "headless": self.settings.headless,
                "slow_mo": self.settings.slow_mo_ms,
            }
            if self.settings.browser_channel:
                launch_options["channel"] = self.settings.browser_channel
            if self.settings.browser_cdp_url:
                self._browser = self._playwright.chromium.connect_over_cdp(
                    self.settings.browser_cdp_url
                )
                self._connected_over_cdp = True
                contexts = self._browser.contexts
                if not contexts:
                    raise ConfigurationError("Nenhum contexto encontrado no Chrome")
                self._context = contexts[0]
                return
            context_options = {
                "locale": "pt-BR",
                "timezone_id": "America/Sao_Paulo",
                "viewport": {"width": 1440, "height": 1000},
            }
            if self.settings.browser_user_data_dir:
                user_data_dir = Path(self.settings.browser_user_data_dir).expanduser()
                self._context = self._playwright.chromium.launch_persistent_context(
                    str(user_data_dir), **launch_options, **context_options
                )
                for page in self._context.pages:
                    if page.url == "about:blank":
                        page.close()
            else:
                self._browser = self._playwright.chromium.launch(**launch_options)
                self._context = self._browser.new_context(**context_options)
        except Exception as exc:
            self.close()
            if self.settings.browser_cdp_url:
                raise ConfigurationError(
                    f"Nao foi possivel conectar ao Chrome em "
                    f"{self.settings.browser_cdp_url}. Feche todas as janelas "
                    "do Chrome e inicie uma instancia com "
                    "--remote-debugging-port=9222 e um --user-data-dir "
                    "dedicado; depois confirme a porta 9222 e tente novamente."
                ) from exc
            raise ConfigurationError(
                "Nao foi possivel iniciar o Chromium. Execute: "
                "python -m playwright install chromium"
            ) from exc

    def close(self) -> None:
        if self._context is not None and not self._connected_over_cdp:
            self._context.close()
            self._context = None
        elif self._connected_over_cdp:
            self._context = None
        if self._browser is not None and not self._connected_over_cdp:
            self._browser.close()
            self._browser = None
        elif self._browser is not None:
            self._browser = None
            self._connected_over_cdp = False
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def collect_cards(
        self,
        provider_name: str,
        url: str,
        selectors: SiteSelectors,
        limit: int,
    ) -> list[BrowserProductCard]:
        if self._context is None:
            raise ConfigurationError("Browser RPA nao foi iniciado")
        reuse_page = self._connected_over_cdp and bool(self._context.pages)
        page = self._context.pages[0] if reuse_page else self._context.new_page()
        timeout_ms = int(self.settings.browser_timeout_seconds * 1000)
        page.set_default_timeout(timeout_ms)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.locator("body").wait_for(state="visible", timeout=timeout_ms)
            self._dismiss_cookie_banner(page)
            try:
                self._raise_if_blocked(page, provider_name)
            except BrowserBlockedError:
                if not self._request_manual_verification(page, provider_name):
                    raise
            cards = self._find_cards(page, selectors.cards, timeout_ms)
            results: list[BrowserProductCard] = []
            seen: set[str] = set()
            for index in range(min(cards.count(), max(limit * 3, limit))):
                card = cards.nth(index)
                title = self._first_text(card, selectors.titles)
                link = self._first_attribute(card, selectors.links, "href")
                if not title or not link:
                    continue
                purchase_url = urljoin(page.url, link)
                identity = f"{title.casefold()}|{purchase_url}"
                if identity in seen:
                    continue
                seen.add(identity)
                raw_text = self._safe_text(card)
                price_text = self._first_text(card, selectors.prices)
                if not price_text:
                    price_text = self._price_from_text(raw_text)
                results.append(
                    BrowserProductCard(
                        title=title,
                        price_text=price_text,
                        purchase_url=purchase_url,
                        description=self._first_text(card, selectors.descriptions),
                        seller=self._first_text(card, selectors.sellers),
                        image_url=self._absolute_attribute(
                            page, card, selectors.images, "src"
                        ),
                        raw_text=raw_text,
                    )
                )
                if len(results) >= limit:
                    break
            return results
        except BrowserBlockedError:
            raise
        except PlaywrightTimeoutError as exc:
            raise ProviderError(
                f"{provider_name}: a pagina nao carregou dentro do tempo limite"
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"{provider_name}: falha durante a navegacao RPA") from exc
        finally:
            if not reuse_page:
                page.close()

    @staticmethod
    def _dismiss_cookie_banner(page: Page) -> None:
        for label in ("Aceitar tudo", "Aceitar todos", "Concordo", "Accept all"):
            button = page.get_by_role("button", name=label, exact=True)
            try:
                if button.count() and button.first.is_visible():
                    button.first.click(timeout=1500)
                    return
            except PlaywrightTimeoutError:
                continue

    @staticmethod
    def _raise_if_blocked(page: Page, provider_name: str) -> None:
        body = BrowserRpa._safe_text(page.locator("body"))
        normalized = re.sub(r"\s+", " ", body.casefold())
        if any(marker in normalized for marker in BLOCK_MARKERS):
            raise BrowserBlockedError(
                f"{provider_name}: bloqueio ou CAPTCHA detectado; "
                "o RPA nao tenta contornar a protecao"
            )

    def _request_manual_verification(self, page: Page, provider_name: str) -> bool:
        if self.settings.headless and not self.settings.browser_cdp_url:
            return False
        print(
            f"{provider_name}: bloqueio/CAPTCHA detectado. Resolva manualmente "
            f"na aba aberta e pressione Enter (ate {MANUAL_VERIFICATION_ATTEMPTS} tentativas)."
        )
        for attempt in range(1, MANUAL_VERIFICATION_ATTEMPTS + 1):
            try:
                input(f"Tentativa {attempt}/{MANUAL_VERIFICATION_ATTEMPTS} - pressione Enter apos resolver: ")
            except EOFError:
                return False
            try:
                self._raise_if_blocked(page, provider_name)
            except BrowserBlockedError:
                if attempt < MANUAL_VERIFICATION_ATTEMPTS:
                    print("A protecao ainda esta presente; conclua a verificacao na aba.")
                    continue
                return False
            return True
        return False

    @staticmethod
    def _find_cards(page: Page, selectors: tuple[str, ...], timeout_ms: int) -> Locator:
        combined = page.locator(", ".join(selectors))
        try:
            combined.first.wait_for(state="visible", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            return combined
        return combined

    @staticmethod
    def _first_text(root: Locator, selectors: tuple[str, ...]) -> str | None:
        for selector in selectors:
            locator = root.locator(selector).first
            try:
                if locator.count() and locator.is_visible():
                    text = locator.inner_text(timeout=1000).strip()
                    if text:
                        return text
            except PlaywrightTimeoutError:
                continue
        return None

    @staticmethod
    def _first_attribute(root: Locator, selectors: tuple[str, ...], name: str) -> str | None:
        for selector in selectors:
            locator = root.locator(selector).first
            try:
                if locator.count():
                    value = locator.get_attribute(name, timeout=1000)
                    if value:
                        return value.strip()
            except PlaywrightTimeoutError:
                continue
        return None

    @staticmethod
    def _absolute_attribute(
        page: Page, root: Locator, selectors: tuple[str, ...], name: str
    ) -> str | None:
        value = BrowserRpa._first_attribute(root, selectors, name)
        return urljoin(page.url, value) if value else None

    @staticmethod
    def _safe_text(locator: Locator) -> str:
        try:
            return locator.inner_text(timeout=3000).strip()
        except PlaywrightTimeoutError:
            return ""

    @staticmethod
    def _price_from_text(text: str) -> str | None:
        match = re.search(r"R\$\s*\d[\d.\s]*(?:,\d{1,2})?", text)
        return match.group(0) if match else None

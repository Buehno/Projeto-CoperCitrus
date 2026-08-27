"""Camada de automacao RPA baseada em Playwright e Chromium."""

from __future__ import annotations

import re
from dataclasses import dataclass
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
            self._browser = self._playwright.chromium.launch(**launch_options)
            self._context = self._browser.new_context(
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 1440, "height": 1000},
            )
        except Exception as exc:
            self.close()
            raise ConfigurationError(
                "Nao foi possivel iniciar o Chromium. Execute: "
                "python -m playwright install chromium"
            ) from exc

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
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
        page = self._context.new_page()
        timeout_ms = int(self.settings.browser_timeout_seconds * 1000)
        page.set_default_timeout(timeout_ms)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.locator("body").wait_for(state="visible", timeout=timeout_ms)
            self._dismiss_cookie_banner(page)
            self._raise_if_blocked(page, provider_name)
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

"""Cobertura da extracao de titulo/link dentro do card.

Usa um DOM falso porque o bug corrigido aqui — nome de um anuncio pareado com o
link de outro — so aparece na navegacao dos elementos, que os demais testes
pulam ao simular `collect_cards` inteiro.
"""

import re
import unittest

from copercitrus_price_collector.browser import BrowserRpa


# --------------------------------------------------------------- DOM falso


class Node:
    def __init__(self, tag, *children, text="", visible=True, **attrs):
        self.tag = tag
        self.text = text
        self.visible = visible
        self.attrs = {name.rstrip("_").replace("_", "-"): v for name, v in attrs.items()}
        self.children = list(children)
        for child in self.children:
            child.parent = self
        self.parent = None

    def inner_text(self):
        if self.text:
            return self.text
        return " ".join(c.inner_text() for c in self.children).strip()

    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()

    def ancestors_or_self(self):
        """Do mais proximo para o mais distante, como o eixo ancestor do XPath."""
        node = self
        while node is not None:
            yield node
            node = node.parent


_SELECTOR = re.compile(
    r"^(?P<tag>[a-zA-Z][\w-]*)?"
    r"(?P<classes>(?:\.[\w-]+)*)"
    r"(?P<attrs>(?:\[[^\]]+\])*)$"
)
_ATTR = re.compile(r"\[([\w-]+)(?:(\*?=)'([^']*)')?\]")


def _matches(node, selector):
    for part in (p.strip() for p in selector.split(",")):
        if _matches_simple(node, part):
            return True
    return False


def _matches_simple(node, selector):
    parsed = _SELECTOR.match(selector)
    if not parsed:
        raise AssertionError(f"seletor nao suportado pelo DOM falso: {selector}")
    if parsed["tag"] and parsed["tag"] != node.tag:
        return False
    for klass in filter(None, parsed["classes"].split(".")):
        if klass not in node.attrs.get("class", "").split():
            return False
    for name, op, value in _ATTR.findall(parsed["attrs"]):
        if name not in node.attrs:
            return False
        if op == "=" and node.attrs[name] != value:
            return False
        if op == "*=" and value not in node.attrs[name]:
            return False
    return True


class FakeLocator:
    """Subconjunto da API de Locator usado por BrowserRpa."""

    def __init__(self, nodes):
        self.nodes = list(nodes)

    def locator(self, selector):
        if selector.startswith("xpath="):
            return self._xpath(selector[len("xpath=") :])
        found = []
        for node in self.nodes:
            for candidate in node.descendants():
                if _matches(candidate, selector):
                    found.append(candidate)
        return FakeLocator(found)

    def _xpath(self, expression):
        if expression != "ancestor-or-self::a[@href][1]":
            raise AssertionError(f"xpath nao suportado: {expression}")
        found = []
        for node in self.nodes:
            for ancestor in node.ancestors_or_self():
                if ancestor.tag == "a" and "href" in ancestor.attrs:
                    found.append(ancestor)
                    break
        return FakeLocator(found)

    @property
    def first(self):
        return FakeLocator(self.nodes[:1])

    def nth(self, index):
        return FakeLocator(self.nodes[index : index + 1])

    def count(self):
        return len(self.nodes)

    def is_visible(self):
        return bool(self.nodes) and self.nodes[0].visible

    def inner_text(self, timeout=None):
        return self.nodes[0].inner_text()

    def get_attribute(self, name, timeout=None):
        return self.nodes[0].attrs.get(name)


TITLES = ("h3", "h2", "[role='heading']")
LINKS = (
    "a[href*='/shopping/product/']",
    "a[href*='/products/']",
    "a[href]",
)


def _extract(card_node):
    """Reproduz o pareamento feito em collect_cards."""
    card = FakeLocator([card_node])
    found = BrowserRpa._first_text_node(card, TITLES)
    title = found[0] if found else None
    node = found[1] if found else None
    return title, BrowserRpa._link_for_title(node, card, LINKS)


# ------------------------------------------------------------------ testes


class TitleLinkPairingTest(unittest.TestCase):
    def test_link_comes_from_the_anchor_wrapping_the_title(self):
        card = Node(
            "div",
            Node("a", Node("span", text="Loja Oficial"), href="/loja/xyz"),
            Node(
                "a",
                Node("h3", text="Mouse Logitech M170"),
                href="/shopping/product/CERTO",
            ),
            role="listitem",
        )

        title, link = _extract(card)

        self.assertEqual("Mouse Logitech M170", title)
        # Antes da correcao o link vinha da primeira ancora do card (/loja/xyz).
        self.assertEqual("/shopping/product/CERTO", link)

    def test_container_with_two_products_keeps_each_name_with_its_own_link(self):
        def card_for(nome, href):
            return Node("a", Node("h3", text=nome), href=href)

        primeiro = card_for("Produto A", "/shopping/product/AAA")
        segundo = card_for("Produto B", "/shopping/product/BBB")
        Node("div", primeiro, segundo, role="listitem")

        self.assertEqual(
            ("Produto A", "/shopping/product/AAA"), _extract(primeiro)
        )
        self.assertEqual(
            ("Produto B", "/shopping/product/BBB"), _extract(segundo)
        )

    def test_image_anchor_before_the_title_does_not_win(self):
        card = Node(
            "div",
            Node("a", Node("img", src="/foto.jpg"), href="/imagem/redirect"),
            Node("a", Node("h3", text="Oleo 1L"), href="/shopping/product/OLEO"),
            role="listitem",
        )

        self.assertEqual(("Oleo 1L", "/shopping/product/OLEO"), _extract(card))

    def test_falls_back_to_card_selectors_when_title_is_outside_any_anchor(self):
        card = Node(
            "div",
            Node("h3", text="Produto sem link no titulo"),
            Node("a", text="comprar", href="/shopping/product/FALLBACK"),
            role="listitem",
        )

        title, link = _extract(card)

        self.assertEqual("Produto sem link no titulo", title)
        self.assertEqual("/shopping/product/FALLBACK", link)

    def test_specific_selector_wins_over_generic_in_the_fallback(self):
        card = Node(
            "div",
            Node("h3", text="Produto"),
            Node("a", text="loja", href="/seller/abc"),
            Node("a", text="ver", href="/shopping/product/ESPECIFICO"),
            role="listitem",
        )

        self.assertEqual("/shopping/product/ESPECIFICO", _extract(card)[1])

    def test_card_without_any_link_yields_none(self):
        card = Node("div", Node("h3", text="Produto"), role="listitem")

        self.assertEqual(("Produto", None), _extract(card))

    def test_invisible_title_is_skipped(self):
        card = Node(
            "div",
            Node("a", Node("h3", text="Oculto", visible=False), href="/oculto"),
            Node("a", Node("h2", text="Visivel"), href="/shopping/product/OK"),
            role="listitem",
        )

        self.assertEqual(("Visivel", "/shopping/product/OK"), _extract(card))


class GoogleSelectorOrderTest(unittest.TestCase):
    def test_generic_anchor_is_the_last_option(self):
        from copercitrus_price_collector.providers.google_shopping import (
            GOOGLE_SELECTORS,
        )

        self.assertEqual("a[href]", GOOGLE_SELECTORS.links[-1])
        self.assertIn("/shopping/product/", GOOGLE_SELECTORS.links[0])

    def test_shopee_keeps_specific_first(self):
        from copercitrus_price_collector.providers.shopee_affiliate import (
            SHOPEE_SELECTORS,
        )

        self.assertEqual("a[href]", SHOPEE_SELECTORS.links[-1])


if __name__ == "__main__":
    unittest.main()

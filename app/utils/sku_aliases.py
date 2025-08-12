ALIAS_MAP: dict[str, str] = {
    "VALERY-PACK-2-NO-SMELL": "Пакеты по 2 шт.",
    "VALERY-PACK-5-NO-SMELL": "Пакеты по 5 шт.",
    "VALERY-PACK-8-NO-SMELL": "Пакеты по 8 шт.",
    "VALERY-CARDS-1": "Карточки для фотосессии",
    "GOOD-CONDITION-1": "Кронштейны для кондиционера",
}


def alias_sku(sku: str) -> str:
    if not isinstance(sku, str):
        try:
            sku = str(sku)
        except Exception:
            return "SKU"
    return ALIAS_MAP.get(sku, sku)

# Пользовательский порядок отображения (по алиасам)
ALIAS_ORDER: list[str] = [
    "Кронштейны для кондиционера",
    "Карточки для фотосессии",
    "Пакеты по 8 шт.",
    "Пакеты по 5 шт.",
    "Пакеты по 2 шт.",
]

_ORDER_INDEX = {name: idx for idx, name in enumerate(ALIAS_ORDER)}


def sort_pairs_by_alias(pairs: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Сортирует пары (name, value) по пользовательскому порядку алиасов.

    Неизвестные алиасы идут после известных, с вторичной сортировкой по имени.
    """
    return sorted(pairs, key=lambda p: (_ORDER_INDEX.get(p[0], 10_000), p[0]))



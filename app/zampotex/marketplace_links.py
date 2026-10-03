from urllib.parse import quote

from zampotex.models import Car


def _q(text: str) -> str:
    return quote(text.strip(), safe="")


def search_phrase(car: Car, query: str | None = None) -> str:
    base = f"{car.brand} {car.model} {car.year}".strip()
    if query and query.strip():
        return f"{base} {query.strip()}"
    return base


def marketplace_url_buttons(car: Car, query: str | None = None) -> list[tuple[str, str]]:
    """Исходящие ссылки на поиск у агрегаторов (без парсинга и без API)."""
    phrase = search_phrase(car, query)
    vin = car.vin.upper()
    return [
        ("Exist · VIN", f"https://www.exist.ru/Profile/Vin/GuestQuery"),
        ("Emex", f"https://emex.ru/products/search?text={_q(phrase)}"),
        ("Autodoc", f"https://www.autodoc.ru/search?query={_q(phrase)}"),
        ("Zap.ru", f"https://zap.ru/search?q={_q(phrase)}"),
        ("Яндекс", f"https://yandex.ru/search/?text={_q(phrase + ' купить запчасть')}"),
    ]


def vin_catalog_url_buttons(car: Car) -> list[tuple[str, str]]:
    vin = _q(car.vin)
    return [
        ("NHTSA decode", f"https://vpic.nhtsa.dot.gov/decoder/Decoder?VIN={vin}"),
        ("mcp.vin", f"https://mcp.vin/{vin}"),
    ]

"""Универсальные чек-листы ТО — для любого VIN, без OEM-номеров."""

from zampotex.models import Car


def oil_change_kit_lines(car: Car) -> list[str]:
    engine = car.engine_code or "код двигателя не указан в гараже"
    lines = [
        "Типовой комплект «замена масла» (номера в заказ не подставляются):",
        f"• Моторное масло — объём и допуск смотрите в мануале или в блоке AutoTools ниже; двигатель в гараже: {engine}.",
        "• Фильтр масляный.",
        "• Прокладка или шайба сливной пробки (если одноразовая).",
        "• Сливная пробка — при износе резьбы.",
        "• По регламенту: фильтр салона, фильтр воздушный (если совпадает интервал).",
    ]
    if not car.engine_code:
        lines.append(
            "• Добавьте код двигателя в карточке авто — так проще сузить модификацию в открытых базах."
        )
    return lines


def brake_service_kit_lines() -> list[str]:
    return [
        "Типовой комплект по тормозам (номера в заказ не подставляются):",
        "• Тормозные колодки (перед / зад — как в запросе).",
        "• Тормозные диски — если меняете вместе с колодками.",
        "• Направляющие и пыльники суппорта — по состоянию.",
        "• Тормозная жидкость — если вскрывали контур или по сроку.",
        "• Очиститель и смазка для направляющих (без меди в составе для многих машин).",
    ]


def kit_lines_for_intent(intent: str, car: Car) -> list[str] | None:
    if intent == "oil":
        return oil_change_kit_lines(car)
    if intent in {"brake_pad", "brake_disc", "brake"}:
        return brake_service_kit_lines()
    return None


def format_kit_block(intent: str, car: Car) -> str | None:
    lines = kit_lines_for_intent(intent, car)
    if not lines:
        return None
    return "\n".join(lines)

from zampotex.models import Car
from zampotex.vin_lookup import VinInfo, bmw_type_spec


def car_spec_rows(car: Car, info: VinInfo | None) -> list[tuple[str, str]]:
    """Строки карточки ТС: только то, что известно из гаража и открытого разбора VIN."""
    rows: list[tuple[str, str]] = []
    rows.append(("Кузов № (VIN)", car.vin.upper()))
    rows.append(("Год выпуска", str(car.year)))
    if car.brand:
        rows.append(("Производитель", car.brand))
    if car.model:
        rows.append(("Модель", car.model))

    if info and info.model and info.model != car.model:
        rows.append(("Модификация по открытым базам", info.model))

    spec = bmw_type_spec(car.vin, car.brand)
    if spec:
        rows.append(("Серия / поколение", spec.generation))
        if spec.model:
            rows.append(("Модификация (заводской тип)", spec.model))
        if spec.engine:
            rows.append(("Двигатель (открытый справочник)", spec.engine))
        if spec.power:
            rows.append(("Мощность (справочник)", spec.power))
        if spec.drive:
            rows.append(("Привод", spec.drive))
        if spec.gearbox:
            rows.append(("КПП (справочник)", spec.gearbox))
        if spec.market:
            rows.append(("Рынок (справочник)", spec.market))
    elif info and info.type_code_detail:
        rows.append(("Код типа в VIN", info.type_code_detail))

    if len(car.vin) == 17 and not spec and not (info and info.type_code_detail):
        rows.append(("Знаки 4–7 VIN", car.vin[3:7]))

    if car.engine_code:
        rows.append(("Модель двигателя (из гаража)", car.engine_code))
    if car.power_hp is not None:
        rows.append(("Мощность, л.с.", str(car.power_hp)))
    if car.gearbox:
        box = car.gearbox
        if car.gearbox_code:
            box = f"{box} {car.gearbox_code}"
        rows.append(("КПП (из гаража)", box))

    if info:
        if info.country:
            rows.append(("Страна производителя (WMI)", info.country))
        if info.region and info.region != info.country:
            rows.append(("Регион WMI", info.region))
        if info.bmw_model_year_code is not None:
            rows.append(
                (
                    "Код модельного года BMW",
                    f"{info.bmw_model_year_code} (не всегда год выпуска с конвейера)",
                )
            )
        if info.vehicle_type:
            rows.append(("Тип ТС (NHTSA)", info.vehicle_type))

    if car.city:
        rows.append(("Город эксплуатации", car.city))
    mileage = f"{car.mileage_km} км" if car.mileage_km is not None else None
    if mileage:
        rows.append(("Пробег", mileage))

    return rows

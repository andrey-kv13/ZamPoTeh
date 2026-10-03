import os
import tempfile
import unittest
from pathlib import Path

from zampotex.config import get_settings
from zampotex.formatters import result_messages
from zampotex.models import Car
from zampotex.parsing import detect_side, find_vin, message_is_vin, parse_query, validate_vin, wmi_brand, year_hints
from zampotex.vin_lookup import build_vin_source_lines, expected_check_digit, explain, interpret
from zampotex.open_sources import choose_listed_model, matching_recalls, matching_torque, recall_name_variants, torque_components
from zampotex.car_spec import car_spec_rows
from zampotex.texts import DISCLAIMER, NO_CATALOG_NUMBER


class ParsingTests(unittest.TestCase):
    def test_sample_vin(self):
        vin = find_vin("VIN: XW8ZZZ5NZBG100948")
        self.assertEqual(vin, "XW8ZZZ5NZBG100948")
        self.assertEqual(wmi_brand(vin), "Volkswagen")
        self.assertIn(2011, year_hints(vin, 2026))
        self.assertIsNone(validate_vin("XW8ZZZ5NZBG10094O"))

    def test_side_does_not_treat_fault_word_as_right(self):
        self.assertIsNone(detect_side("неисправность зеркала"))
        self.assertEqual(detect_side("зеркало правое"), "right")
        self.assertEqual(detect_side("фара левая"), "left")

    def test_articles_skip_vin_and_short_years(self):
        parsed = parse_query("сайлентблок 1K0407182 для XW8ZZZ5NZBG100948 2010", "XW8ZZZ5NZBG100948")
        self.assertIn("1K0407182", parsed.articles)
        self.assertNotIn("XW8ZZZ5NZBG100948", parsed.articles)
        self.assertNotIn("2010", parsed.articles)

    def test_result_does_not_invent_numbers(self):
        car = Car(
            user_id=1,
            vin="XW8ZZZ5NZBG100948",
            brand="Volkswagen",
            model="Tiguan",
            year=2010,
            city="Москва",
            engine_code="CBAB",
        )
        parsed = parse_query("передний сайлентблок нижнего рычага", car.vin)
        html_text, plain = result_messages(car, "передний сайлентблок нижнего рычага", parsed, [], False)
        self.assertIn(NO_CATALOG_NUMBER, plain)
        self.assertIn(DISCLAIMER, plain)
        self.assertNotIn("1K0407182", plain)
        self.assertNotIn("1K0407182", html_text)
        self.assertIn("Проверенные открытые источники", plain)

    def test_open_facts_stay_out_of_the_order_list(self):
        hits, detail = matching_recalls(
            {
                "results": [
                    {
                        "NHTSACampaignNumber": "20V314000",
                        "Component": "SERVICE BRAKES",
                        "Summary": "Brake hose may leak.",
                    },
                    {
                        "NHTSACampaignNumber": "19V001000",
                        "Component": "ENGINE",
                        "Summary": "Oil leak.",
                    },
                ]
            },
            "тормозные колодки",
        )
        self.assertEqual(len(hits), 1)
        self.assertIn("20V314000", hits[0].title)
        self.assertIn("совпадений", detail)
        torque_hits, _torque_detail = matching_torque(
            {
                "specs": [
                    {
                        "component": "wheel",
                        "component_label": "Wheel bolts",
                        "torque_nm": "120.0",
                        "model": "3 Series / 5 Series",
                        "note": None,
                    }
                ]
            },
            "530d xDrive",
            "wheel",
        )
        self.assertIn("120.0", torque_hits[0].text)
        self.assertIn("5 Series", torque_hits[0].text)

    def test_brake_discs_use_nearest_bmw_and_bolt_torque(self):
        chosen, exact = choose_listed_model(
            "530d xDrive",
            ["528I", "528I XDRIVE", "535D", "535D XDRIVE", "535I"],
        )
        self.assertEqual(chosen, "535D XDRIVE")
        self.assertFalse(exact)
        self.assertEqual(torque_components("тормозные диски", "part"), ("wheel", "caliper"))
        self.assertEqual(recall_name_variants("535D XDRIVE"), ("535D XDRIVE", "535D"))

    def test_wmi_list_covers_published_codes(self):
        self.assertEqual(wmi_brand("AAVXXXXXXXXXXXXXX"), "Volkswagen")
        self.assertEqual(wmi_brand("X4X5D39490D883173"), "BMW")

    def test_oil_search_includes_universal_kit(self):
        car = Car(user_id=1, vin="JTDBT923000000001", brand="Toyota", model="Corolla", year=2015)
        parsed = parse_query("замена масла", car.vin)
        self.assertEqual(parsed.intent, "oil")
        _, plain = result_messages(car, "замена масла", parsed, [], True)
        self.assertIn("Фильтр масляный", plain)
        self.assertNotIn("1K0", plain)

    def test_car_spec_any_vin_has_vin_row(self):
        car = Car(user_id=1, vin="1HGCM82633A004352", brand="Honda", model="Accord", year=2003, city="Москва")
        rows = dict(car_spec_rows(car, None))
        self.assertEqual(rows["Кузов № (VIN)"], car.vin.upper())
        self.assertEqual(rows["Знаки 4–7 VIN"], "CM82")

    def test_touareg_vin_from_open_base(self):
        vin = "WVGZZZCRZLD039828"
        self.assertEqual(message_is_vin(vin), vin)
        self.assertIsNone(message_is_vin(f"{vin} и ещё текст"))
        info = interpret(
            vin,
            {
                "Make": "VOLKSWAGEN",
                "Model": "",
                "ModelYear": "2020",
                "VehicleType": "MULTIPURPOSE PASSENGER VEHICLE (MPV)",
            },
            2026,
        )
        self.assertEqual(info.brand, "Volkswagen")
        self.assertEqual(info.model, "Touareg")
        self.assertTrue(info.model_from_type_code)
        self.assertEqual(info.year, 2020)
        self.assertFalse(info.check_digit_ok)
        self.assertNotEqual(expected_check_digit(vin), "Z")

    def test_avtotor_bmw_missing_from_nhtsa(self):
        vin = "X4X5D39490D883173"
        info = interpret(vin, {"Make": "", "Model": "", "ModelYear": ""}, 2026)
        self.assertEqual(info.brand, "BMW")
        self.assertEqual(info.model, "530d xDrive")
        self.assertEqual(info.type_code_kind, "bmw")
        self.assertTrue(info.model_from_type_code)
        self.assertTrue(info.nhtsa_make_missing)
        self.assertIsNone(info.year)
        self.assertEqual(info.bmw_model_year_code, 2013)
        self.assertTrue(info.check_digit_ok)
        info.source_lines = build_vin_source_lines(
            info,
            {"Make": ""},
            {
                "validation": {
                    "wmi": {"code": "X4X", "country": "Russia", "region": "Europe"},
                    "checksum": {"valid": True},
                }
            },
            {"missing": True},
        )
        text = explain(info)
        self.assertIn("Автотор", text)
        self.assertIn("530d xDrive", text)
        self.assertIn("F10 LCI", text)
        self.assertIn("N57", text)
        self.assertIn("258", text)
        self.assertIn("Россия", text)
        self.assertIn("2013", text)
        self.assertIn("СТС", text)
        self.assertIn("ETK", text)
        self.assertIn("mcp.vin", text)
        self.assertIn("DB.VIN", text)
        self.assertIn("Международный WMI", text)

    def test_world_wmi_decodes_non_us_vin(self):
        info = interpret("VF1LM1B0H36666155", None, 2026)
        self.assertEqual(info.country, "Франция")
        self.assertEqual(info.region, "Европа")
        self.assertEqual(info.brand, "Renault")
        self.assertEqual(info.model, "Megan II")
        self.assertEqual(info.type_code_kind, "world")
        text = explain(info)
        self.assertIn("все страны", text)
        self.assertNotIn("VAG", text)

    def test_known_check_digit(self):
        self.assertEqual(expected_check_digit("1HGCM82633A004352"), "3")

    def test_admins_and_bot_id(self):
        settings = get_settings()
        self.assertEqual(settings.bot_id, 8893240032)
        self.assertEqual(settings.admins, frozenset({170051092, 311684774, 206146757, 635342790}))


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + Path(self._tmp.name, "test.db").as_posix()
        from zampotex import db

        db._engine = None
        db._session_factory = None
        await db.init_db()
        self.db = db

    async def asyncTearDown(self):
        if self.db._engine is not None:
            await self.db._engine.dispose()
        self._tmp.cleanup()

    async def test_delete_car_removes_garage_entry(self):
        from zampotex.repo import count_cars, delete_car, get_car, get_or_create_user

        async with self.db.session_factory()() as session:
            user = await get_or_create_user(session, 42, "Test")
            car = Car(user_id=user.id, vin="WBADT43452G123456", brand="BMW", model="3", year=2012, city="Казань")
            session.add(car)
            await session.commit()
            car_id = car.id

        async with self.db.session_factory()() as session:
            user = await get_or_create_user(session, 42, "Test")
            car = await get_car(session, car_id, user.id)
            self.assertIsNotNone(car)
            await delete_car(session, car)
            await session.commit()

        async with self.db.session_factory()() as session:
            user = await get_or_create_user(session, 42, "Test")
            self.assertEqual(await count_cars(session, user.id), 0)
            self.assertIsNone(await get_car(session, car_id, user.id))

    async def test_delete_keeps_technical_vin_history_without_user(self):
        from zampotex.models import Search, User
        from zampotex.repo import delete_account, get_or_create_user

        async with self.db.session_factory()() as session:
            user = await get_or_create_user(session, 170051092, "Админ")
            car = Car(user_id=user.id, vin="XW8ZZZ5NZBG100948", brand="Volkswagen", model="Tiguan", year=2010, city="Москва")
            session.add(car)
            await session.flush()
            session.add(
                Search(
                    user_id=user.id,
                    car_id=car.id,
                    vin=car.vin,
                    text="зеркало левое",
                    status="search_unavailable",
                    summary="пусто",
                    hidden=False,
                )
            )
            await session.commit()
            user_id = user.id

        async with self.db.session_factory()() as session:
            user = await session.get(User, user_id)
            await delete_account(session, user)
            await session.commit()

        async with self.db.session_factory()() as session:
            from sqlalchemy import select

            row = (await session.execute(select(Search).where(Search.vin == "XW8ZZZ5NZBG100948"))).scalar_one()
            self.assertIsNone(row.user_id)
            self.assertEqual(row.text, "зеркало левое")


if __name__ == "__main__":
    unittest.main()

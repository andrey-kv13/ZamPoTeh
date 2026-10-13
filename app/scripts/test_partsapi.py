"""Проверка PartsAPI: python -m scripts.test_partsapi VIN"""

from __future__ import annotations

import sys

from zampotex.partsapi_client import summarize_vindecode, vindecode, vindecode_oe


def main() -> None:
    vin = (sys.argv[1] if len(sys.argv) > 1 else "WVGZZZCRZLD039828").upper()
    print(f"VIN: {vin}")
    dec = vindecode(vin)
    print("VINdecode:", summarize_vindecode(dec) or "(нет ответа — проверьте PARTSAPI_KEY_VINDECODE)")
    oe = vindecode_oe(vin)
    if oe is not None:
        print("VINdecodeOE: ответ получен")
    else:
        print("VINdecodeOE: нет ключа или ошибка")


if __name__ == "__main__":
    main()

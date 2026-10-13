# PartsAPI — настройка ключей

У [PartsAPI](https://partsapi.ru) **отдельный ключ на каждый купленный метод**. Имя метода в личном кабинете совпадает с URL:  
`https://partsapi.ru/method/VINdecode?key=...&vin=...&lang=ru`

## Переменные в `app/.env`

Скопируйте ключ из ЛК в нужную строку (в git не коммитить):

```env
PARTSAPI_KEY_VINDECODE=
PARTSAPI_KEY_VINDECODEOE=
PARTSAPI_KEY_GETSEARCHTREE=
PARTSAPI_KEY_GETARTICLES=
PARTSAPI_KEY_GETARTICLE=
PARTSAPI_KEY_GETARTICLECROSSES=
PARTSAPI_KEY_TOPARTS=
PARTSAPI_KEY_TOOILS=
```

Pydantic читает их как `partsapi_key_vindecode` и т.д.

## Проверка из консоли

```bash
cd app
python -m scripts.test_partsapi WVGZZZCRZLD039828
```

## Бот

При заданном `PARTSAPI_KEY_VINDECODE` блок «PartsAPI TecDoc VINdecode» появится в карточке VIN (`vin_lookup.lookup_vin`).

Номера запчастей для заказа по-прежнему только когда подключите цепочку getSearchTree / getArticles в поиске.

## Безопасность

Ключи не отправляйте в чат и не публикуйте в GitHub. Если ключ засветился — перевыпустите в ЛК PartsAPI.

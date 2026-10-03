# ZamPoTeh (ЗамПоТех)

Telegram-бот [@ZamPoTehProBot](https://t.me/ZamPoTehProBot) — гараж по VIN, поиск запчастей своими словами, история по VIN, стеллаж, напоминания. Backend рассчитан на общий код с будущим мобильным приложением.

## Структура репозитория

```
├── app/                    # Python-приложение (aiogram 3)
│   ├── zampotex/           # пакет бота
│   ├── tests/              # unit-тесты
│   ├── scripts/            # деплой на VPS (опционально)
│   ├── requirements.txt
│   └── .env.example
├── deploy/                 # примеры для production
├── docs/                   # документация для разработчиков
└── .github/workflows/      # CI
```

## Быстрый старт (разработка)

```bash
cd app
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # вставить BOT_TOKEN от @BotFather
python -m zampotex
```

## Конфигурация

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | Токен бота (обязательно) |
| `BOT_ID` | `8893240032` |
| `ADMIN_IDS` | Telegram user id админов через запятую |
| `DATABASE_URL` | По умолчанию SQLite в `app/data/` |

## Тесты

```bash
cd app
python -m unittest discover -s tests -v
```

## Production

- Один процесс long polling на токен (не запускать локально и на VPS одновременно).
- Пример unit systemd: [deploy/zampotex.service.example](deploy/zampotex.service.example).
- Деплой: `scripts/deploy_vps.py` (нужен `pip install -r requirements-dev.txt`, пароль только в env `VPS_PASS`).

Подробная архитектура: [docs/architecture-bot.html](docs/architecture-bot.html).

## Продуктовые правила

- Не выдавать OEM-номера, цены и аналоги без лицензированного каталога (очередь 2).
- Открытые источники — с явной пометкой; disclaimer в каждом результате поиска.

## Лицензия

Проприетарный код проекта ЗамПоТех. Уточняйте у правообладателя перед коммерческим использованием.

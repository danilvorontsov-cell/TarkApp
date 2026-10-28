# Инструкция по деплою TarkApp на Zone VPS

**Целевой хост:** `uvn-235-67.ams01.zonevs.eu`

Ветка `deploy/zone-vps` содержит готовую серверную конфигурацию для запуска бэкенда FastAPI, Nginx с раздачей лендинга и проксированием API, а также персистентного тома для базы данных SQLite `tarkapp.db`.

---

## 1. Первичное подключение к серверу по SSH

```bash
ssh root@uvn-235-67.ams01.zonevs.eu
```

---

## 2. Клонирование репозитория на сервере

```bash
# Клонируем ветку deploy/zone-vps
git clone -b deploy/zone-vps https://github.com/danilvorontsov-cell/TarkApp.git
cd TarkApp
```

---

## 3. Настройка переменных окружения

Скопируйте пример файла конфигурации:
```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Обязательно укажите:
- `GEMINI_API_KEY=ваш_ключ_google_gemini`
- `TELEGRAM_BOT_TOKEN=` (если настроен бот оповещений)
- `TELEGRAM_CHAT_ID=` (если настроены алерты)
- `RESEND_API_KEY=` или `SMTP_*` (для отправки PDF-счетов)

---

## 4. Запуск через автоматический скрипт

Сделайте скрипт исполняемым и запустите его:
```bash
chmod +x deploy/setup.sh
./deploy/setup.sh
```

Скрипт автоматически:
1. Проверит и установит Docker / Docker Compose (при необходимости).
2. Соберет образ FastAPI бэкенда.
3. Запустит контейнеры `backend` и `nginx`.
4. Дождётся успешного прохождения healthcheck (`/health`).

---

## 5. Проверка работы

- **Лендинг:** [http://uvn-235-67.ams01.zonevs.eu](http://uvn-235-67.ams01.zonevs.eu)
- **API Healthcheck:** [http://uvn-235-67.ams01.zonevs.eu/health](http://uvn-235-67.ams01.zonevs.eu/health)
- **Интерактивная документация:** [http://uvn-235-67.ams01.zonevs.eu/docs](http://uvn-235-67.ams01.zonevs.eu/docs)

---

## 6. Полезные команды управления

```bash
# Просмотр логов в реальном времени
docker compose logs -f

# Генерация промо-ключей на сервере (например, 10 ключей по 30 дней)
docker compose exec backend python scripts/generate_keys.py --count 10 --days 30

# Перезапуск стека
docker compose restart

# Остановка стека
docker compose down
```

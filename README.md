# Peak Zone Manual Trigger Validation Dashboard

Streamlit-приложение, которое **валидирует вручную записанное время срабатывания Layer 2 / Peak Zone**, используя firmware-совместимую логику.

> Приложение **не ищет** первый момент, в который выполнились все 5 условий Layer 2. Оно только проверяет, были ли условия выполнены в указанное вручную время.

Подробная спецификация: [`streamlit_peakzone_cursor_spec_v4_firmware_compatible.md`](streamlit_peakzone_cursor_spec_v4_firmware_compatible.md).

---

## Структура проекта

```
peakzone-dashboard/
├── app.py
├── config.py
├── requirements.txt
├── README.md
│
├── data/
│   ├── logs/
│   │   ├── session_001.json
│   │   └── session_002.json
│   └── metadata/
│       └── sessions_metadata.csv
│
├── src/
│   ├── data_loader.py
│   ├── preprocessing.py
│   ├── peak_analysis.py
│   ├── layer2_validation.py
│   ├── metrics.py
│   └── plots.py
│
├── scripts/
│   └── generate_sample_logs.py
│
├── tests/
│   ├── test_peak_analysis.py
│   ├── test_layer2_validation.py
│   └── test_timezone_parsing.py
│
└── outputs/
    └── peakzone_validation_results.csv   # генерируется на скачивании
```

---

## Установка

На macOS используйте `python3` (команды `python` без цифры может не быть).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

После активации venv внутри неё `python` и `pip` уже работают (symlink на python3).

## Быстрый старт (local mode)

1. Активируйте venv (один раз на сессию терминала):

   ```bash
   source .venv/bin/activate
   ```

2. Сгенерируйте демонстрационные логи (один раз для проекта):

   ```bash
   python scripts/generate_sample_logs.py
   ```

3. Запустите Streamlit:

   ```bash
   streamlit run app.py
   ```

4. В sidebar выберите `Data source = local`. Метаданные читаются из `data/metadata/sessions_metadata.csv`, логи — из `data/logs/*.json`.

## GitHub raw mode

1. Установите переменную окружения с базой raw URL:

   ```bash
   export GITHUB_RAW_BASE_URL="https://raw.githubusercontent.com/<owner>/<repo>/<branch>"
   ```

2. Запустите приложение и в sidebar выберите `Data source = github_raw`.

В этом режиме `data_loader` ходит за `data/metadata/sessions_metadata.csv` и `data/logs/*.json` напрямую через `requests`.

> **GitHub — это источник истории.** Кэш Streamlit (`@st.cache_data`) используется только для ускорения и **не** хранит историю.

---

## Метаданные

Файл `data/metadata/sessions_metadata.json` — массив объектов.

**Вручную нужно заполнять только три поля:**

| Поле | Обязательно? | Что писать |
|---|---|---|
| `session_id` | да | Уникальный ID (по умолчанию = имя файла без `.json`) |
| `log_file` | да | Имя JSON-файла лога (без `data/logs/`) |
| `manual_peakzone_entry_time` | да | Время Peak Zone, записанное вручную |
| `notes` | нет | Произвольный комментарий |

**Авто-извлекается из лога** (писать не нужно):
- `device_id` — ищется в корне или в секции `metadata` / `meta` / `info` / `session` / `device`
- `mode` — `mode` / `program` / `recipe` / `cycle`
- `start_time` / `end_time` — первая и последняя метка времени в записях

**Авто-считается из логов**:
- `real_peak_time`, `real_peak_height`
- `peak_start_time`, `peak_end_time`, `peak_duration_minutes`
- `t100_time`, `t100_reached`
- Все диагностические значения Layer 2

### Пример

```json
[
  {
    "session_id": "session_005",
    "log_file": "session_005.json",
    "manual_peakzone_entry_time": "2026-05-25 16:42:00"
  },
  {
    "session_id": "session_006",
    "log_file": "session_006.json",
    "manual_peakzone_entry_time": "2026-05-26 14:10:00",
    "notes": "Sensor noisy near peak"
  }
]
```

Все naive-таймстемпы трактуются как `Asia/Seoul`. Отдельной колонки timezone нет.

### Не помнишь формат? Используй вкладку **Add Session**

В приложении есть вкладка **Add Session**, которая:

1. Показывает список JSON-файлов в `data/logs/`, которых ещё нет в metadata.
2. Парсит выбранный лог, показывает `device_id`, `start_time`, `real_peak_time` и график высоты.
3. Даёт готовый JSON-блок с `session_id` и `log_file` уже заполненными — тебе остаётся только выбрать дату/время Peak Zone (мышью в date/time pickers).
4. Копируешь блок и вставляешь в `sessions_metadata.json`.

---

## Тесты

```bash
source .venv/bin/activate
pytest -q
```

Покрытие:

- `test_peak_analysis.py` — `peak_end` устойчив к одиночным шумовым провалам, срабатывает на 5-минутном устойчивом падении, не выходит за `real_peak_time`.
- `test_layer2_validation.py` — все 5 firmware-совместимых условий, `validation_status` enum, ±90 с lookup для `height_10min_ago`.
- `test_timezone_parsing.py` — naive → Asia/Seoul, UTC → Asia/Seoul, неравномерные таймстемпы.

---

## Deploy on Streamlit Community Cloud

1. Открой [share.streamlit.io](https://share.streamlit.io) и залогинься через GitHub.
2. Нажми **Create app** → **Deploy a public app from GitHub**.
3. Заполни:
   - **Repository**: `<your-username>/quick_mode_peak_zone`
   - **Branch**: `main`
   - **Main file path**: `app.py`
4. (Опционально) **Advanced settings** → **Python version** = `3.11`. Эта же версия зафиксирована в `runtime.txt`.
5. Нажми **Deploy**.

Через 1–2 минуты приложение поднимется на `https://<your-app-slug>.streamlit.app`.

### Как добавлять данные после деплоя

GitHub — это persistent storage для истории сессий (см. спецификацию, раздел 3).

**Workflow добавления одной сессии:**

1. Положи JSON-лог в `data/logs/<имя>.json`. Минимальный формат:

   ```json
   {
     "device_id": "SourFriend-A494",
     "mode": "Quick",
     "records": [
       {"timestamp": "2026-05-25 09:00:00", "height_mm": 18.0, "temperature_c": 26.0},
       {"timestamp": "2026-05-25 09:05:00", "height_mm": 18.4, "temperature_c": 26.1}
     ]
   }
   ```

   `device_id` и `mode` в корне — опционально (приложение их подтянет). Поддерживаемые алиасы для высоты: `height` / `current_height` / `sensor_height` / `measured_height`; для времени: `time` / `created_at` / `measured_at` / `datetime`. Naive-таймстемпы → `Asia/Seoul`.

2. Закоммить лог и пушни:

   ```bash
   git add data/logs/<имя>.json
   git commit -m "data: add log <имя>"
   git push
   ```

3. Откройся в задеплоенном приложении → вкладка **Add Session**. Там увидишь свой новый лог. Выбери дату/время Peak Zone, скопируй сгенерированный JSON-блок.

4. Вставь блок в `data/metadata/sessions_metadata.json` (внутри массива `[...]`), закоммить и пушни:

   ```bash
   git add data/metadata/sessions_metadata.json
   git commit -m "data: register session <id>"
   git push
   ```

5. Streamlit Cloud автоматически перезапустит приложение через 1–2 минуты. Можно форсировать в **Manage app → Reboot app**.

### Альтернативный режим: `github_raw`

Если хочется, чтобы приложение тянуло файлы напрямую из raw-GitHub (без коммита в текущий репо приложения):

1. В sidebar переключи **Data source** в `github_raw`.
2. Задай `GITHUB_RAW_BASE_URL` в переменных окружения деплоя (Streamlit Cloud → **Settings** → **Secrets**):

   ```toml
   GITHUB_RAW_BASE_URL = "https://raw.githubusercontent.com/<owner>/<repo>/<branch>"
   ```

3. Файлы `data/logs/*.json` и `data/metadata/sessions_metadata.csv` должны лежать по этому пути.

---

## Конфигурация (sidebar или `config.py`)

| Параметр | Default |
|---|---|
| `PEAK_PLATEAU_DROP_THRESHOLD_MM` | `3.0` |
| `PEAK_END_BELOW_THRESHOLD_MINUTES` | `5` |
| `MANUAL_TRIGGER_TOLERANCE_MINUTES` | `2` |
| `HEIGHT_10MIN_LOOKUP_TOLERANCE_SECONDS` | `90` |
| `DEFAULT_TIMEZONE` | `Asia/Seoul` |

---

## Firmware-совместимость (важно)

- **Condition 1** — current point **включён** в окно `recent_max_30min`.
- **Condition 2** — **signed** разница `current − height_10min_ago` (не `abs()`). Падение высоты автоматически даёт `True`.
- **Condition 4** — если `max_slope_last_60min <= 0`, условие **passes**.
- **Condition 5** — boolean `t100_reached`, диагностика `time_since_t100_min` хранится отдельно.

Эти решения зафиксированы в v4-спецификации, разделы 8–9.

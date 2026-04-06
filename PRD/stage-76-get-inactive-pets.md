# PRD: Этап 76 — Инструмент get_inactive_pets

## Цель
Поиск питомцев, не посещавших клинику N месяцев.

## API
- `get_inactive_pets(months: int, limit: int = 50)` → list of pets
- months: количество месяцев без визита (default 6)
- Алгоритм:
  1. Вычислить cutoff_date = today - months
  2. Получить все admissions после cutoff (paginate_all, admission)
  3. Собрать set(patient_id) активных питомцев
  4. Получить всех питомцев (paginate_all, pet)
  5. Вернуть тех, чей id NOT IN active set
  6. Ограничить limit

## Ограничения
- Для клиник с >10000 питомцев может быть медленно — документировать
- Используем серверную фильтрацию admissions по дате через API filter

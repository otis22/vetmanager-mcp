# PRD: Этап 180. Landing ChatGPT connector copy simplification

## Контекст

Пользователь указал, что текущий блок лендинга про ChatGPT звучит как
инструкция: "Можно подключить прямо к ChatGPT ... Создать аккаунт и подключить
ChatGPT". Для лендинга нужен более короткий второй вариант:

- заголовок: "Работает прямо в ChatGPT";
- текст: "Подключите сервис через готовый MCP connector. Без ручных токенов, с
  безопасным доступом по умолчанию.";
- CTA: "Подключить".

## Scope

In:

- Заменить copy только в существующей секции `#chatgpt-connector`.
- Обновить тесты, которые закрепляют landing copy.
- Не менять OAuth, account UI, consent presets, scopes или runtime behavior.

Out:

- Редизайн лендинга.
- Изменение account onboarding.
- Изменение ChatGPT connector/OAuth behavior.

## Архитектурное решение

Проблема: текущий текст слишком подробный для лендинга и дублирует кабинетную
инструкцию.

Контекст и ограничения:

- Лендинг рендерится inline в `landing_page.py`.
- Stage 177 уже реализовал OAuth/preset безопасность; эта задача меняет только
  публичную формулировку.
- CTA остаётся ссылкой на `/register`, потому лендинг не определяет auth state.

Рассмотренные варианты:

- Переписать весь ChatGPT/onboarding блок: избыточно для copy-hotfix.
- Заменить только заголовок и два предложения в `#chatgpt-connector`: минимально
  и соответствует запросу.

Выбранное решение: заменить текст секции на второй короткий вариант и сохранить
тестовую защиту от упоминания ручного bearer/token flow внутри секции.

Инварианты:

- Секция `#chatgpt-connector` остаётся на странице и в навигации.
- В секции не появляется ручной bearer token language.
- Security promise остаётся точным: безопасный доступ по умолчанию, без обещания
  write access.

Rollback/fallback: вернуть предыдущий текст секции в `landing_page.py`, если
новая формулировка окажется слишком короткой для конверсии.

Architecture Critique: not required, потому что задача не меняет auth, storage,
API/MCP contract, runtime behavior или cross-module ownership boundary.

## Acceptance Criteria

1. Лендинг содержит заголовок `Работает прямо в ChatGPT`.
2. ChatGPT-секция содержит текст `Подключите сервис через готовый MCP connector.`
3. ChatGPT-секция содержит текст `Без ручных токенов, с безопасным доступом по умолчанию.`
4. CTA в ChatGPT-секции называется `Подключить` и ведёт на `/register`.
5. В ChatGPT-секции нет manual credential language: `Bearer`, `API key`,
   `service token`, `service bearer`.
6. Regression test закрепляет новый заголовок, оба предложения, CTA и отсутствие
   manual credential language в ChatGPT-секции.
7. Тесты лендинга проходят.

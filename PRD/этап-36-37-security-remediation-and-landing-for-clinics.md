# PRD: Этапы 36–37. Security remediation и landing page для клиник

## Контекст

После этапов 32–35 web-контур уже:
- поддерживает account registration/login/logout;
- хранит Vetmanager integration;
- выпускает service bearer-токены;
- показывает privacy/auth transparency;
- поддерживает `login/password -> user token` exchange.

Но остаются два разных блока работ:

1. Security remediation:
- нет полноценной CSRF protection для web forms;
- нет отдельного brute-force/rate limiting для `/login` и `/register`;
- нет явного набора security headers для web UI.

2. Landing page:
- главная страница всё ещё звучит слишком developer-centric;
- в hero нет продуктово выделенной регистрации как главного CTA;
- подача пока не оптимизирована под ветврачей, администраторов и руководителей клиник.

## Цели

### Этап 36
- Добавить CSRF protection для всех state-changing web forms.
- Добавить rate limiting для `/register` и `/login`.
- Добавить базовые security headers для web responses.
- Подтвердить, что logout/login flow не ломается после hardening.

### Этап 37
- Переписать landing page на языке пользы для клиники.
- Сделать регистрацию главным CTA на первом экране.
- Уменьшить акцент на developer tooling и Cursor.
- Оставить технический блок ниже страницы как secondary information.

## Нецели

- Полноценная CAPTCHA / email verification.
- Полноценный server-side session store.
- Многостраничный маркетинговый сайт.
- Отдельная CMS для landing content.

## Решения

### 1. CSRF protection

- Использовать signed double-submit token:
  - GET responses с form'ами выставляют `vm_csrf` cookie;
  - HTML form содержит hidden input `csrf_token`;
  - POST handler проверяет совпадение hidden field и signed cookie token;
  - token подписывается тем же app secret, что и web session.
- Применить к:
  - `/register`
  - `/login`
  - `/logout`
  - `/account/integration`
  - `/account/integration/reauth`
  - `/account/tokens`
  - `/account/tokens/{id}/revoke`

### 2. Web auth rate limiting

- Реализовать process-local sliding-window limiter.
- Ключи:
  - для `/login`: IP + normalized email
  - для `/register`: IP
- На превышение лимита возвращать `429` и безопасное сообщение без утечки деталей.

### 3. Security headers

- Для HTML responses добавить:
  - `Content-Security-Policy`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: no-referrer`
  - `X-Content-Type-Options: nosniff`
- `Strict-Transport-Security` включать только при явном production env flag / secure mode.

### 4. Landing page

- Hero должен отвечать на вопрос:
  - что это даёт клинике;
  - кому это помогает;
  - как быстро начать.
- Основной CTA:
  - `Зарегистрироваться`
- Secondary CTA:
  - `Войти`
- Убрать упор на Cursor и developer language из hero.
- Добавить блок:
  - для кого сервис;
  - примеры практических запросов;
  - короткий technical block ниже страницы.

## Декомпозиция

### Этап 36
- 36.1 tests на CSRF missing/mismatch.
- 36.2 tests на rate limiting `/login` и `/register`.
- 36.3 tests на security headers.
- 36.4 реализация CSRF helpers и web response helpers.
- 36.5 реализация limiter и integration в routes.
- 36.6 update README/AssumptionLog.

### Этап 37
- 37.1 tests на landing copy и CTA.
- 37.2 переписать landing copy.
- 37.3 browser-check desktop/mobile.
- 37.4 update README/AssumptionLog/Roadmap.

## Критерии готовности

- POST forms без valid CSRF token отвергаются.
- `/login` и `/register` возвращают `429` при превышении лимита.
- HTML responses содержат базовые security headers.
- Landing page явно ориентирована на ветврачей и руководителей клиник.
- Регистрация визуально и смыслово главный CTA.
- Tests и browser-check подтверждают новый контракт.

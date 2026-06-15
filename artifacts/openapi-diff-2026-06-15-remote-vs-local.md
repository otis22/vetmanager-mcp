# OpenAPI diff: published Swagger UI vs local artifact — 2026-06-15

## Sources

- Remote: `https://otis22.github.io/vetmanager-openapi/vetmanager_openapi_v6.yaml`
- Remote SHA-256: `224674f31dd3ffe9f79612ce3dec7de506a655c2093f8ce27eeae933d02bfb5c`
- Local: `artifacts/vetmanager_openapi_v6.json`
- Local SHA-256: `e2c40cc34ee4f3324d10a600b4a6de710ccf45f053ff99e2ff9b1bec62283c9e`

## Summary

- Local: OpenAPI `3.0.0`, title `VetManager REST API (v6 - Real Responses)`, version `1.2.0`, paths `101`, operations `129`, schemas `36`.
- Remote: OpenAPI `3.0.0`, title `VetManager REST API`, version `1.3.1`, paths `103`, operations `136`, schemas `36`.
- Operation delta: `+31` added, `-24` removed, `105` changed among common operations; net `7` operations.
- Schema delta: `+0` added, `-0` removed, `11` changed among common schemas.
- Servers/security/securitySchemes are unchanged by structure.
- The remote artifact is structurally newer, but contains real-looking email/password-hash examples that the local artifact has sanitized.

## High-level interpretation

1. The remote spec fixes many path-shape problems from the local artifact: trailing-slash paths and hardcoded example IDs are replaced with canonical collection paths or `{id}` path parameters.
2. The remote spec adds new endpoint families: `goodTag`, `report-ai-job`, and parameterized `VmLink` links.
3. Schema names are unchanged, so adopting the remote spec would mostly affect paths/operation metadata/nullable flags rather than adding new component models.
4. Before replacing the local artifact, remote examples need the same privacy sanitization policy as the current local file.

## Added operations in remote

- `+ GET /rest/api/PartyAccount` — GetAllParty
- `+ GET /rest/api/PartyAccountDoc` — GetAllPartyAccountDoc
- `+ GET /rest/api/StoreDocument` — GetAllStoreDocuments
- `+ GET /rest/api/Suppliers` — GetAllSuppliers
- `+ POST /rest/api/Suppliers` — CreateSupplier
- `+ GET /rest/api/VmLink/personalAccountLinkByClientId/{clientId}` — Get By ID
- `+ GET /rest/api/VmLink/personalAccountLinkByPhone/{phone}` — Get By Phone
- `+ POST /rest/api/admission` — Post Admission
- `+ GET /rest/api/anonymousClient/{id}` — Get Client By ID
- `+ GET /rest/api/city/{id}` — Get City By ID
- `+ GET /rest/api/client/{id}` — Get Client By ID
- `+ GET /rest/api/clinics` — Get All Clinics
- `+ GET /rest/api/goodGroup/{id}` — GoodGroup Get By ID
- `+ GET /rest/api/goodTag` — Get All Good Tags
- `+ POST /rest/api/goodTag` — Create Good Tag
- `+ DELETE /rest/api/goodTag/{id}` — Delete Good Tag
- `+ GET /rest/api/goodTag/{id}` — Get Good Tag By Id
- `+ PUT /rest/api/goodTag/{id}` — Update Good Tag By Id
- `+ GET /rest/api/payment` — Get Payments By Invoice ID (Filter)
- `+ DELETE /rest/api/pet/{id}` — Delete Pet
- `+ GET /rest/api/pet/{id}` — Get Pet By ID
- `+ POST /rest/api/report-ai-job` — Create Report AI Job
- `+ GET /rest/api/report-ai-job/{id}` — Get Report AI Job By ID
- `+ POST /rest/api/report-ai-job/{id}/confirm` — Confirm Report AI Job Candidate
- `+ GET /rest/api/report-ai-job/{id}/data` — Get Report AI Job Data
- `+ POST /rest/api/report-ai-job/{id}/save` — Save Report AI Job
- `+ GET /rest/api/role/{id}` — Get Role By ID
- `+ GET /rest/api/stores/RestOfGoodInWarehouse` — GetQuantityGood
- `+ POST /rest/api/street` — Post Street
- `+ GET /rest/api/timesheet` — Get All TimeSheets
- `+ GET /rest/api/unit/{id}` — Get Unit By ID

## Removed operations from local

- `- GET /rest/api/ComboManualName/` — Get Combo Manual Names. Remote has `/rest/api/ComboManualName`.
- `- GET /rest/api/PartyAccount/` — GetAllParty. Remote has `/rest/api/PartyAccount`.
- `- GET /rest/api/PartyAccountDoc/` — GetAllPartyAccountDoc. Remote has `/rest/api/PartyAccountDoc`.
- `- GET /rest/api/StoreDocument/` — GetAllStoreDocuments. Remote has `/rest/api/StoreDocument`.
- `- GET /rest/api/Suppliers/` — GetAllSuppliers. Remote has `/rest/api/Suppliers`.
- `- POST /rest/api/Suppliers/` — CreateSupplier. Remote has `/rest/api/Suppliers`.
- `- GET /rest/api/VmLink/personalAccountLinkByClientId/1` — Get By ID (With Auth #2).
- `- GET /rest/api/VmLink/personalAccountLinkByPhone/3322122` — Get By Phone.
- `- GET /rest/api/admission/` — GetAllAdmission. Remote has `/rest/api/admission`.
- `- POST /rest/api/admission/` — Post Admission. Remote has `/rest/api/admission`.
- `- GET /rest/api/anonymousClient/116468` — Get Client By ID. Remote has `/rest/api/anonymousClient/{id}`.
- `- GET /rest/api/city/255` — Get City By ID. Remote has `/rest/api/city/{id}`.
- `- GET /rest/api/client/116468` — Get Client By ID. Remote has `/rest/api/client/{id}`.
- `- GET /rest/api/clinics/` — Get All Clinics. Remote has `/rest/api/clinics`.
- `- GET /rest/api/goodGroup/9` — GoodGroup Get By ID. Remote has `/rest/api/goodGroup/{id}`.
- `- GET /rest/api/payment/` — Get Payments By Invoice ID (Filter). Remote has `/rest/api/payment`.
- `- GET /rest/api/pet/` — Get All Pets By Owner Id And Not Deleted. Remote has `/rest/api/pet`.
- `- DELETE /rest/api/pet/122` — Delete Pet. Remote has `/rest/api/pet/{id}`.
- `- GET /rest/api/pet/74` — Get Pet By ID. Remote has `/rest/api/pet/{id}`.
- `- GET /rest/api/role/2` — Get Role By ID. Remote has `/rest/api/role/{id}`.
- `- GET /rest/api/stores/RestOfGoodInWarehouse/` — GetQuantityGood. Remote has `/rest/api/stores/RestOfGoodInWarehouse`.
- `- POST /rest/api/street/` — Post Street. Remote has `/rest/api/street`.
- `- GET /rest/api/timesheet/` — Get All TimeSheets. Remote has `/rest/api/timesheet`.
- `- GET /rest/api/unit/1` — Get Unit By ID. Remote has `/rest/api/unit/{id}`.

## Changed common operations

- `* GET /rest/api/ComboManualItem` — changed: `operationId, tags, parameters, responses`
- `* POST /rest/api/ComboManualItem` — changed: `operationId, tags, requestBody, responses`
- `* GET /rest/api/ComboManualItem/{ID}` — changed: `operationId, tags, parameters, responses`
- `* PUT /rest/api/ComboManualItem/{ID}` — changed: `operationId, tags, requestBody, responses`
- `* GET /rest/api/ComboManualName` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/ComboManualName/{ID}` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/GoodGroup` — changed: `operationId, tags, responses`
- `* POST /rest/api/GoodGroup` — changed: `operationId, tags, requestBody, responses`
- `* DELETE /rest/api/GoodGroup/{ID}` — changed: `operationId, tags, responses`
- `* PUT /rest/api/GoodGroup/{ID}` — changed: `operationId, tags, requestBody, responses`
- `* GET /rest/api/HospitalBlock` — changed: `operationId, tags, responses`
- `* GET /rest/api/HospitalBlock/{ID}` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/MedicalCards` — changed: `summary, operationId, tags, responses`
- `* POST /rest/api/MedicalCards` — changed: `operationId, tags, requestBody, responses`
- `* POST /rest/api/MedicalCards/AddVaccination` — changed: `operationId, tags, parameters, requestBody, responses`
- `* GET /rest/api/MedicalCards/AllDiagnoses` — changed: `operationId, tags, responses`
- `* GET /rest/api/MedicalCards/MedcardsTextTemplates` — changed: `operationId, tags, responses`
- `* GET /rest/api/MedicalCards/MedicalcardsDataByClient` — changed: `summary, operationId, tags, parameters, responses`
- `* GET /rest/api/MedicalCards/Vaccinations` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/MedicalCards/{ID}` — changed: `operationId, tags, parameters, responses`
- `* PUT /rest/api/MedicalCards/{ID}` — changed: `operationId, tags, requestBody, responses`
- `* GET /rest/api/PartyAccount/{ID}` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/PartyAccountDoc/{ID}` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/StoreDocument/{ID}` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/StoreDocumentOperation/{ID}` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/Suppliers/{ID}` — changed: `operationId, tags, parameters, responses`
- `* POST /rest/api/Unit` — changed: `operationId, tags, requestBody, responses`
- `* DELETE /rest/api/Unit/{ID}` — changed: `operationId, tags, responses`
- `* PUT /rest/api/Unit/{ID}` — changed: `operationId, tags, requestBody, responses`
- `* GET /rest/api/admission` — changed: `operationId, tags, parameters`
- `* DELETE /rest/api/admission/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/admission/{ID}` — changed: `summary, operationId, tags, parameters`
- `* PUT /rest/api/admission/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/anonymousClient` — changed: `operationId, tags`
- `* GET /rest/api/breed` — changed: `summary, operationId, tags`
- `* GET /rest/api/breed/{ID}` — changed: `operationId, tags, parameters`
- `* GET /rest/api/cassa` — changed: `operationId, tags`
- `* GET /rest/api/cassa/{ID}` — changed: `operationId, tags, parameters`
- `* GET /rest/api/cassaclose` — changed: `operationId, tags`
- `* GET /rest/api/cassaclose/{ID}` — changed: `operationId, tags, parameters`
- `* GET /rest/api/cassarashod` — changed: `operationId, tags, responses`
- `* GET /rest/api/cassarashod/{ID}` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/city` — changed: `operationId, tags`
- `* POST /rest/api/city` — changed: `operationId, tags`
- `* DELETE /rest/api/city/{ID}` — changed: `operationId, tags`
- `* PUT /rest/api/city/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/cityType` — changed: `operationId, tags`
- `* POST /rest/api/cityType` — changed: `operationId, tags`
- `* DELETE /rest/api/cityType/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/cityType/{ID}` — changed: `operationId, tags, parameters`
- `* PUT /rest/api/cityType/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/client` — changed: `operationId, tags`
- `* DELETE /rest/api/client/{ID}` — changed: `operationId, tags`
- `* POST /rest/api/client/{ID}` — changed: `operationId, tags`
- `* PUT /rest/api/client/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/clinics/{ID}` — changed: `operationId, tags, parameters`
- `* GET /rest/api/closingOfInvoices` — changed: `operationId, tags`
- `* GET /rest/api/closingOfInvoices/{ID}` — changed: `operationId, tags, parameters`
- `* GET /rest/api/fiscalRegisterData` — changed: `operationId, tags, responses`
- `* GET /rest/api/fiscalRegisterData/{ID}` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/fiscalTaxSystems` — changed: `operationId, tags, responses`
- `* GET /rest/api/fiscalTaxSystems/{ID}` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/good` — changed: `operationId, tags`
- `* POST /rest/api/good` — changed: `operationId, tags`
- `* DELETE /rest/api/good/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/good/{ID}` — changed: `operationId, tags, parameters`
- `* PUT /rest/api/good/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/goodSaleParam` — changed: `summary, operationId, tags`
- `* PUT /rest/api/goodSaleParam/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/hospital` — changed: `operationId, tags`
- `* GET /rest/api/hospital/{ID}` — changed: `operationId, tags, parameters`
- `* PUT /rest/api/hospital/{ID}` — changed: `operationId, tags, requestBody`
- `* GET /rest/api/invoice` — changed: `operationId, tags`
- `* GET /rest/api/invoice/{ID}` — changed: `operationId, tags, parameters`
- `* GET /rest/api/invoiceDocument` — changed: `operationId, tags, parameters`
- `* GET /rest/api/invoiceDocument/{ID}` — changed: `operationId, tags, parameters`
- `* POST /rest/api/messages/all` — changed: `operationId, tags, requestBody, responses`
- `* GET /rest/api/messages/reports` — changed: `operationId, tags, parameters, responses`
- `* POST /rest/api/messages/roles` — changed: `operationId, tags, requestBody, responses`
- `* POST /rest/api/messages/users` — changed: `operationId, tags, requestBody, responses`
- `* GET /rest/api/payment/{ID}` — changed: `operationId, tags, parameters`
- `* GET /rest/api/pet` — changed: `summary, operationId, tags, parameters`
- `* POST /rest/api/pet` — changed: `operationId, tags`
- `* PUT /rest/api/pet/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/petType` — changed: `operationId, tags`
- `* GET /rest/api/petType/{ID}` — changed: `operationId, tags, parameters`
- `* GET /rest/api/properties` — changed: `operationId, tags`
- `* GET /rest/api/report/StartReport` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/report/reportFile` — changed: `operationId, tags, parameters, responses`
- `* GET /rest/api/role` — changed: `operationId, tags`
- `* GET /rest/api/street` — changed: `summary, operationId, tags`
- `* DELETE /rest/api/street/{ID}` — changed: `operationId, tags`
- `* PUT /rest/api/street/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/timesheet/{ID}` — changed: `operationId, tags, parameters`
- `* GET /rest/api/unit` — changed: `operationId, tags`
- `* GET /rest/api/user` — changed: `operationId, tags`
- `* GET /rest/api/user/anonymousList` — changed: `operationId, tags`
- `* GET /rest/api/user/{ID}` — changed: `summary, operationId, tags, parameters`
- `* PUT /rest/api/user/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/userPosition` — changed: `operationId, tags`
- `* POST /rest/api/userPosition` — changed: `operationId, tags`
- `* DELETE /rest/api/userPosition/{ID}` — changed: `operationId, tags`
- `* GET /rest/api/userPosition/{ID}` — changed: `operationId, tags, parameters`
- `* PUT /rest/api/userPosition/{ID}` — changed: `operationId, tags`
- `* POST /token_auth.php` — changed: `operationId, tags, requestBody, responses`

## Schema changes

- Added schemas: none.
- Removed schemas: none.

Changed schemas:
- `admission` — props changed: `client`
- `cassaclose` — props changed: `closedUser`
- `client` — props changed: `email`
- `closingOfInvoices` — props changed: `client`, `client_id`
- `comboManualName` — props changed: `id`, `is_readonly`, `name`, `title`
- `diagnoses` — props changed: `id`, `status`, `title`
- `hospital` — props changed: `client_data`, `doctor_data`
- `invoice` — props changed: `client`, `doctor`
- `medicalcards` — props changed: `full_text`, `title`
- `pet` — props changed: `owner`
- `user` — props changed: `email`, `passwd`

## Notable schema field differences

- `closingOfInvoices`: `client` example differs; `client_id` nullable `False` -> `True`
- `medicalcards`: `full_text` nullable `True` -> `False`; `title` nullable `True` -> `False`
- `comboManualName`: `id` nullable `None` -> `False`; `is_readonly` nullable `None` -> `False`; `name` nullable `None` -> `False`; `title` nullable `None` -> `False`
- `diagnoses`: `id` nullable `None` -> `False`; `status` nullable `None` -> `False`; `title` nullable `None` -> `False`
- `client`: `email` example differs
- `user`: `email` example differs; `passwd` example differs
- `invoice`: `client` example differs; `doctor` example differs
- `pet`: `owner` example differs
- `hospital`: `client_data` example differs; `doctor_data` example differs
- `admission`: `client` example differs
- `cassaclose`: `closedUser` example differs

## Privacy/sanitization check

- Remote unique email-like strings: `6`.
- Local unique email-like strings: `3`.
- Remote unique 32-hex strings: `1`.
- Local unique 32-hex strings: `1`.
- Remote examples include real-looking addresses and password-hash-shaped values; do not publish/import as-is without running the project privacy sanitizer/checks.

## Recheck commands

```bash
curl -fsSL https://otis22.github.io/vetmanager-openapi/vetmanager_openapi_v6.yaml -o /tmp/vetmanager_openapi_remote_refetch.yaml
python3 - <<'PY'
# Load local JSON and remote YAML, then compare paths/methods/components structurally.
PY
```

## Recommendation

Use the remote spec as the better route/operation baseline, but merge it through a sanitization step and then re-run contract/privacy checks before replacing `artifacts/vetmanager_openapi_v6.json`.

## Product decisions after review

- `goodTag` differences are handled by Stage 169: invoice-ready goods search with ordinary non-template combinations and server-side combination price calculation. No `goodTag` write tools.
- `report-ai-job` differences are handled by Stage 170: prompt helper, async job tools, explicit save, and data retrieval only after `saved`/`existing_report_matched`.
- `VmLink` differences should become Stage 171: expose only phone-based personal-account link lookup. The client-ID endpoint exists in OpenAPI/source but must not be exposed as MCP because the user approved links only when the assistant already knows the client's phone.
- Added parameterized `GET /rest/api/client/{id}` and `GET /rest/api/pet/{id}` do not require new convenience tools. User explicitly decided not to add separate `get_client_by_id` / `get_pet_by_id` tools.

## VmLink research notes

Source files:

- `/home/otis/myprojects/vetmanager-extjs/rest/protected/controllers/VmLinkController.php`
- `/home/otis/myprojects/vetmanager-extjs/application/src/ServiceIntegration/VmLink.php`

Controller endpoints:

- `doCustomRestGetPersonalAccountLinkByClientId($clientId)` returns `data.vetmanagerLink.personal_link` or `success=false`.
- `doCustomRestGetPersonalAccountLinkByPhone($phone)` returns the same shape.

MCP decision:

- Add only `get_personal_account_link_by_phone(phone)`.
- Normalize input phone to digits before calling Vetmanager.
- Call `GET /rest/api/VmLink/personalAccountLinkByPhone/{digits}`.
- Treat returned `personal_link` as sensitive persistent output.
- Do not add `get_personal_account_link_by_client_id`.

Verified on `devtr6` on 2026-06-15:

- Formatted `client.cell_phone` in path returned a route-level 404.
- Digits-only phone for the same client returned HTTP 200, `data.vetmanagerLink.success=true`, and a personal link.
- Missing digits-only phone returned HTTP 200, top-level `success=true`, message `Client profile not found`, and `data.vetmanagerLink.success=false`.
- Full links and phone values were intentionally not written to this artifact.

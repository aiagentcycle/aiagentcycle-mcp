# Contentvelden

Eigenaarsdata in `content-published/`; de bestanden in `content-templates/` zijn schema-voorbeelden zonder echte gegevens.

| Bestand | Velden |
| --- | --- |
| `profile.{nl,en}.json` | `lang`, `name`, `status`, `summary`, `legal_name`, `kvk`, `location`, `founder`, `key_facts[]`, `focus[]`, `approach`, `website`, `sources[]`, `verify` (`page_id`, `strings[]`), `updated` |
| `services.json` | `price_terms`, `source`, `verify_page_id`, `services[]` met `id`, `name`, `name_en`, `summary`, `price`, `verify[]`, `url`, `public`. Sleutels `internal`, `internal_notes`, `cost`, `margin`, `owner_only` en sleutels die met `_` beginnen gaan eruit. |
| `faq.{nl,en}.json` | `lang`, `status`, `source`, `updated`, `items[]` met `id`, `q`, `a`. Schrijft de sync elk uur uit de FAQPage-JSON-LD. |
| `contact.json` | `status`, `website`, `scan`, `contact_page`, `email`, `phone`, `company`, `note` |
| `kb/*.md` | frontmatter `id`, `slug`, `type` (article, page, integration, case, solution, sector), `modified`, `link`, `lang`, `title`, `summary`, daarna een titel en Markdown-tekst. Alleen de sync schrijft deze map. |

`verify`: elke tekst moet letterlijk (hoofdletterongevoelig, witruimte genormaliseerd) in de gesynchroniseerde bronpagina staan. Zo niet, dan geven de tools `price_verified: false` of `facts_verified: false` en wordt de dagelijkse AAC-check rood: pas dan dit bestand aan.

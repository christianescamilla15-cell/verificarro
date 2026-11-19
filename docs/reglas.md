# Reglas de negocio → pruebas

Ésta es la compuerta real de calidad (más que el % de cobertura): cada regla del dominio tiene al menos una
prueba que falla si la regla se rompe. Las referencias usan `archivo::prueba` relativo a `backend/tests/`;
`test_reglas_doc.py` verifica que cada prueba citada aquí exista (y corre en el CI).

Para agregar una regla: escribe la prueba primero, agrégala a la tabla y corre `pytest`.

## 1. VIN (ISO 3779 / 49 CFR 565) · `app/analyzers/vin_decoder.py`

| # | Regla | Pruebas |
|---|---|---|
| V1 | El VIN se normaliza (mayúsculas, sin guiones ni espacios) antes de validar | `test_vin_decoder.py::test_normalize_vin`, `test_vin_decoder.py::test_normalized_vin_checksum_matches_reference` |
| V2 | Exactamente 17 caracteres | `test_vin_decoder.py::test_decode_too_short_invalid_format`, `test_vin_decoder.py::test_decode_too_long_invalid_format` |
| V3 | I, O y Q prohibidas en cualquier posición | `test_vin_decoder.py::test_decode_contains_letter_I_invalid`, `test_vin_decoder.py::test_decode_contains_letter_O_invalid`, `test_vin_decoder.py::test_decode_contains_letter_Q_invalid` |
| V4 | Dígito verificador (posición 9): transliteración + pesos, módulo 11 | `test_vin_decoder.py::test_decode_valid_checksum_known_vin`, `test_vin_decoder.py::test_decode_invalid_checksum_emits_warning`, `test_vin_decoder.py::test_exactly_one_check_digit_is_valid` |
| V5 | Resto 10 se escribe «X» (un «0» en su lugar es inválido) | `test_vin_decoder.py::test_check_digit_x_means_remainder_10` |
| V6 | Año modelo (posición 10) con ciclo decidido por la posición 7 (número → 1980-2009, letra → 2010-2039) | `test_vin_decoder.py::test_decode_year_extraction`, `test_vin_decoder.py::test_year_cycle_disambiguated_by_position_7` |
| V7 | U, Z y 0 no son códigos de año: año sin decodificar, formato válido | `test_vin_decoder.py::test_year_codes_not_in_standard_yield_none` |
| V8 | Fabricante por WMI con marcas hermanas (Honda↔Acura, Toyota↔Lexus); WMI desconocido no es alarma | `test_vin_decoder.py::test_decode_honda_wmi_2hg`, `test_vin_decoder.py::test_honda_5j8_decodes_acura`, `test_vin_decoder.py::test_lexus_jth_alias`, `test_vin_decoder.py::test_decode_unknown_wmi_no_alarm` |
| V9 | Respaldo por prefijo de 2 caracteres sólo si hay ≥3 WMI con ese prefijo | `test_vin_decoder.py::test_wmi_two_char_fallback_needs_three_entries` |

## 2. VIN físico contra el anuncio · `app/analyzers/vin_check.py`

| # | Regla | Pruebas |
|---|---|---|
| C1 | Marca del VIN distinta a la del anuncio = alerta alta (posible placa clonada); marcas hermanas sí coinciden | `test_vin_check.py::test_make_mismatch_high_alert`, `test_vin_check.py::test_make_alias_match_no_alert` |
| C2 | Año: ±1 baja (modelo vs fabricación), 2-3 media, >3 alta | `test_vin_check.py::test_year_within_tolerance_low_alert_only`, `test_vin_check.py::test_year_off_by_2_medium_alert`, `test_vin_check.py::test_year_off_by_5_high_alert` |
| C3 | VIN en la descripción distinto al físico = alta y sin coincidencia | `test_vin_check.py::test_vin_in_description_extracted_and_compared`, `test_vin_check.py::test_any_high_alert_breaks_match_even_if_make_and_year_match`, `test_vin_check.py::test_vin_in_description_match_no_alert` |
| C4 | VIN consultado en REPUVE distinto al físico = alta (clonación) | `test_vin_check.py::test_repuve_vin_mismatch_high_alert`, `test_vin_check.py::test_repuve_vin_match_no_alert`, `test_vin_check.py::test_repuve_without_vin_no_alert` |
| C5 | Formato inválido = alta y sin coincidencia | `test_vin_check.py::test_short_vin_returns_high_alert_no_match`, `test_vin_check.py::test_vin_with_prohibited_char_high_alert` |
| C6 | Checksum inválido = alerta media informativa que no decide la coincidencia | `test_vin_check.py::test_invalid_checksum_is_medium_and_does_not_decide_match` |
| C7 | El VIN escaneado se normaliza antes de comparar | `test_vin_check.py::test_scanned_vin_is_normalized_before_comparing`, `test_vin_check.py::test_valid_vin_matching_listing_has_no_alerts` |
| C8 | NHTSA (oficial) confirma marca y carrocería; si no responde, se sigue con el decoder local | `test_nhtsa.py::test_check_with_enrichment_make_mismatch_via_nhtsa`, `test_nhtsa.py::test_check_with_enrichment_body_class_mismatch_alerts`, `test_nhtsa.py::test_check_with_enrichment_no_nhtsa_falls_back`, `test_nhtsa.py::test_decode_vin_returns_none_on_timeout` |

## 3. Consultas a registros oficiales

| # | Regla | Pruebas |
|---|---|---|
| R1 | REPUVE: «robado», «sin reportes», «no encontrado» y situación legal irregular se interpretan del HTML oficial | `test_repuve_parser.py::test_parse_response_robado`, `test_repuve_parser.py::test_parse_response_sin_reportes`, `test_repuve_parser.py::test_parse_response_no_encontrado`, `test_repuve_parser.py::test_parse_response_situacion_legal_irregular` |
| R2 | Placa y NIV se validan antes de consultar | `test_repuve_parser.py::test_is_valid_plate`, `test_repuve_parser.py::test_is_valid_vin`, `test_repuve_remote_dispatch.py::test_query_invalid_input_short_circuits_before_dispatch` |
| R3 | Con `REPUVE_SCRAPER_URL` la consulta va al sidecar con token Bearer; sus fallas degradan sin excepción | `test_repuve_remote_dispatch.py::test_query_dispatches_to_remote_when_scraper_url_set`, `test_repuve_remote_dispatch.py::test_query_remote_includes_bearer_when_token_set`, `test_repuve_remote_dispatch.py::test_query_remote_handles_timeout_gracefully` |
| R4 | El sidecar exige token y placa o VIN | `test_scraper_main.py::test_scrape_with_wrong_token_returns_401`, `test_scraper_main.py::test_scrape_without_token_env_returns_503`, `test_scraper_main.py::test_scrape_without_plate_or_vin_returns_400` |
| R5 | Captura/PDF de REPUVE se lee con el mismo parser canónico | `test_repuve_screenshot_endpoint.py::test_screenshot_robado_parsed_via_canonical_parser`, `test_repuve_screenshot_endpoint.py::test_screenshot_requires_plate_or_vin`, `test_repuve_screenshot_endpoint.py::test_screenshot_validates_image_size_limit` |
| R6 | REPUVE capturado a mano reemplaza la consulta automática | `test_repuve_pipeline.py::test_repuve_manual_override_stolen`, `test_repuve_pipeline.py::test_repuve_manual_override_clean` |
| R7 | Preview: requiere placa o VIN; sin respuesta de REPUVE se topa en 50/amarillo y el resumen dice «pendiente» | `test_registros.py::test_preview_requires_plate_or_vin`, `test_registros.py::test_preview_without_repuve_is_capped_to_yellow_50`, `test_scan_plate.py::test_scan_plate_captcha_returns_yellow_capped_preview` |
| R8 | Preview: robado → rojo; limpio → puede ser verde; legal irregular se nombra en el resumen | `test_registros.py::test_preview_stolen_is_red_with_alert`, `test_registros.py::test_preview_clean_repuve_can_be_green`, `test_registros.py::test_preview_legal_irregular_is_called_out_in_summary`, `test_scan_plate.py::test_scan_plate_stolen_returns_red` |
| R9 | SAT: factura cancelada o inexistente = bandera grave; vigente no castiga | `test_registros.py::test_sat_cancelled_or_missing_invoice_is_high_flag`, `test_registros.py::test_sat_valid_invoice_adds_no_flag`, `test_sat_verify.py::test_parse_cancelado`, `test_sat_verify.py::test_parse_no_encontrado` |
| R10 | SAT: UUID inválido o servicio caído no rompen el reporte | `test_sat_verify.py::test_verify_cfdi_invalid_uuid_returns_error`, `test_sat_verify.py::test_verify_cfdi_handles_timeout` |
| R11 | Factura vs anuncio: marca/modelo distintos = alta; año ±1 sin alerta, 2-3 media, >3 alta; VIN distinto = alta | `test_invoice_validator.py::test_make_mismatch_high`, `test_invoice_validator.py::test_model_mismatch_high`, `test_invoice_validator.py::test_year_diff_2_3_medium`, `test_invoice_validator.py::test_year_diff_more_than_3_high`, `test_invoice_validator.py::test_vin_mismatch_high` |

## 4. Puntaje y nivel de riesgo · `app/analyzers/scoring.py`

| # | Regla | Pruebas |
|---|---|---|
| S1 | Verde ≥ 70, amarillo 40-69, rojo < 40 (límites inclusivos) | `test_scoring.py::test_risk_level_boundaries` |
| S2 | Robado = -50 y rojo siempre (interruptor), sin sumar además la situación legal | `test_scoring.py::test_stolen_vehicle_drops_to_red`, `test_scoring.py::test_stolen_penalty_is_terminal_not_cumulative_with_legal` |
| S3 | Situación legal irregular = -25; REPUVE no consultado no castiga | `test_scoring.py::test_repuve_legal_irregular_penalty_25`, `test_scoring.py::test_repuve_not_queried_has_no_penalty` |
| S4 | Precio ≥ +30 % = -10; ≤ -30 % = -15 (umbrales inclusivos); sin precio justo no castiga | `test_scoring.py::test_price_thresholds_are_inclusive`, `test_scoring.py::test_price_without_fair_price_has_no_penalty`, `test_scoring.py::test_too_cheap_red_flag` |
| S5 | Fotos/descripción: alta -10 (tope 30), media -3 (tope 15), baja -1 (tope 5) | `test_scoring.py::test_high_findings_capped_at_30`, `test_scoring.py::test_medium_findings_3_each_capped_at_15`, `test_scoring.py::test_low_findings_capped` |
| S6 | Vendedor: alta -15 (tope 30), media -5 (tope 15), baja informativa | `test_scoring.py::test_seller_penalties_and_caps` |
| S7 | VIN: alta -25 (tope 50) y rojo siempre; media -8 (tope 16); baja informativa | `test_scoring.py::test_vin_penalties_and_caps`, `test_scoring.py::test_vin_high_alert_kill_switch_forces_red`, `test_scoring.py::test_vin_low_alert_no_kill_switch` |
| S8 | El puntaje nunca baja de 0 | `test_scoring.py::test_score_never_below_zero` |
| S9 | El resumen cierra con una recomendación según el riesgo | `test_scoring.py::test_populate_summary_includes_recommendation` |

## 5. Análisis del anuncio

| # | Regla | Pruebas |
|---|---|---|
| A1 | Descripción: urgencia, vendedor en el extranjero, anticipo por envío de dinero y «no se puede ver» son banderas | `test_description_analyzer.py::test_seller_abroad_high`, `test_description_analyzer.py::test_advance_payment_western_union`, `test_description_analyzer.py::test_no_inspection_allowed`, `test_description_analyzer.py::test_classic_scam_has_high_severity_findings` |
| A2 | Cuenta del vendedor < 30 días = alta, < 90 días = media | `test_seller_analyzer.py::test_new_account_under_30_days_is_high`, `test_seller_analyzer.py::test_new_account_under_90_days_is_medium` |
| A3 | Precio justo = mediana de comparables con tolerancias que se relajan si no hay suficientes | `test_price_estimator.py::test_estimate_returns_median_within_tolerance`, `test_price_estimator.py::test_estimate_relaxes_tolerance_when_strict_filter_empty`, `test_price_estimator.py::test_estimate_empty_pool` |
| A4 | Foto reciclada de otro anuncio (pHash cercano, distinto anuncio) se detecta | `test_photo_dedup.py::test_match_found_with_different_listing_hash`, `test_photo_dedup.py::test_no_match_with_same_listing_hash`, `test_photo_dedup.py::test_no_match_when_hamming_too_high` |
| A5 | EXIF: edición con software o foto vieja frente a un anuncio reciente se señalan | `test_exif_analyzer.py::test_analyze_batch_detects_photoshop_edit`, `test_exif_analyzer.py::test_analyze_batch_old_photo_vs_recent_listing` |

## 6. Estados

| # | Regla | Pruebas |
|---|---|---|
| E1 | Todo estado de pago tiene fila en las tablas de transición | `test_estados.py::test_every_status_has_a_transition_row` |
| E2 | Pago único: pending → paid/failed/refunded; failed → pending/paid (reintento); paid → refunded | `test_estados.py::test_payment_valid_transitions`, `test_estados.py::test_webhook_failed_then_approved_retry_is_accepted`, `test_estados.py::test_webhook_paid_to_refunded_is_accepted`, `test_payments.py::test_webhook_payment_approved_updates_status` |
| E3 | Inválidas: paid → pending/failed (webhook atrasado de otro intento) y todo desde refunded; se ignoran con 200 sin encolar el pipeline | `test_estados.py::test_payment_invalid_transitions`, `test_estados.py::test_webhook_stale_attempt_cannot_unpay_a_paid_payment`, `test_estados.py::test_webhook_refunded_is_terminal` |
| E4 | Webhook duplicado = no-op idempotente | `test_estados.py::test_same_status_is_not_a_transition`, `test_payments.py::test_webhook_idempotent_duplicate_does_nothing`, `test_subscribe.py::test_webhook_preapproval_idempotent_duplicate` |
| E5 | Suscripción: pending → paid/failed; paid → pending (pausa)/failed (cancelación); cancelada es terminal | `test_estados.py::test_subscription_transitions`, `test_estados.py::test_subscription_pause_moves_paid_to_pending`, `test_estados.py::test_subscription_cancelled_cannot_be_reauthorized`, `test_subscribe.py::test_webhook_preapproval_authorized_marks_payment_paid` |
| E6 | Reporte: preview → unlocked sólo con pago en paid; unlocked no vuelve a correr el pipeline | `test_estados.py::test_unlock_requires_paid_payment`, `test_estados.py::test_unlock_preview_to_unlocked_runs_pipeline`, `test_estados.py::test_unlock_already_unlocked_does_not_rerun_pipeline`, `test_scan_plate.py::test_checkout_with_already_unlocked_report_returns_409` |
| E7 | Pagos acreditados sin reporte tras un reinicio se re-encolan (ventana de 30 min, sin suscripciones) | `test_orphan_recovery.py::test_recover_finds_orphan_paid_payment_without_report`, `test_orphan_recovery.py::test_recover_skips_payment_outside_window`, `test_orphan_recovery.py::test_recover_skips_subscription_tiers` |
| E8 | Reporte en caché 24 h por anuncio; vencido se recalcula | `test_report_generator.py::test_cache_hit_for_repeated_listing`, `test_report_generator.py::test_cache_expired_re_runs_pipeline` |

## 7. Pagos, acceso y datos personales

| # | Regla | Pruebas |
|---|---|---|
| P1 | Webhook de MP con firma HMAC válida y dentro de la ventana; si no, 401 | `test_payments.py::test_webhook_with_secret_invalid_signature_returns_401`, `test_payments.py::test_webhook_with_secret_missing_signature_returns_401`, `test_payments.py::test_webhook_replay_window_rejects_old_signature`, `test_payments.py::test_webhook_with_secret_tampered_payment_id_returns_401` |
| P2 | Monto reportado por MP distinto al cobrado (tolerancia 0.01) = no se acredita | `test_estados.py::test_webhook_amount_mismatch_does_not_mark_paid`, `test_estados.py::test_webhook_amount_within_tolerance_is_paid` |
| P3 | Precio por plan: básico 49, premium 99, búsqueda y concesionario por suscripción | `test_payments.py::test_checkout_premium_tier_charges_99`, `test_subscribe.py::test_subscribe_dealer_tier_charges_1499`, `test_subscribe.py::test_subscribe_basic_tier_rejected` |
| P4 | Consultar un pago exige el token de sondeo de ESE pago | `test_payments.py::test_payment_status_without_token_returns_401`, `test_payments.py::test_payment_status_with_token_for_other_payment_returns_401` |
| P5 | Enlace mágico de un solo uso, con vencimiento y consumo atómico | `test_auth.py::test_verify_consumes_token_single_use`, `test_auth.py::test_verify_expired_token_returns_401`, `test_auth.py::test_verify_atomic_consume_returns_401_when_hash_already_cleared` |
| P6 | Placa, VIN y correo del pago se guardan cifrados (Fernet) | `test_crypto.py::test_payment_persists_pii_encrypted_in_db`, `test_crypto.py::test_encrypt_is_non_deterministic` |
| P7 | Límite de solicitudes por IP en endpoints públicos (salud exenta) | `test_rate_limit.py::test_request_link_rate_limit_blocks_after_5`, `test_rate_limit.py::test_health_endpoint_not_rate_limited` |
| P8 | Descarga de fotos sin SSRF (IPs privadas y metadatos de nube bloqueados) | `test_photo_fetcher.py::test_check_url_safe_rejects_unsafe`, `test_photo_fetcher.py::test_fetch_photos_skips_unsafe_urls` |
| P9 | Producción no arranca con JWT_SECRET de ejemplo/corto ni sin FERNET_KEY o MP_WEBHOOK_SECRET | `test_config_produccion.py::test_production_rejects_missing_or_placeholder_secrets`, `test_config_produccion.py::test_non_production_does_not_require_secrets` |

## 8. Operación

| # | Regla | Pruebas |
|---|---|---|
| O1 | La detección de Chromium mira sólo el directorio que usará Playwright | `test_playwright_bootstrap.py::test_browsers_path_defined_ignores_home_cache`, `test_playwright_bootstrap.py::test_default_path_is_home_cache_when_env_unset` |
| O2 | El auto-install de Chromium no bloquea el arranque y se apaga con `PLAYWRIGHT_AUTO_INSTALL=false` | `test_playwright_bootstrap.py::test_ensure_chromium_dispatches_install_when_missing`, `test_playwright_bootstrap.py::test_ensure_chromium_respects_auto_install_switch`, `test_playwright_bootstrap.py::test_ensure_chromium_swallows_unexpected_errors` |
| O3 | La build de Chromium esperada coincide con el Playwright fijado | `test_playwright_bootstrap.py::test_expected_build_matches_installed_playwright` |

## Observaciones abiertas (no se cambiaron)

- **Situación legal irregular queda en verde.** Castiga 25 puntos (100 → 75) y 75 es verde; sólo robo y
  alertas altas de VIN son interruptores a rojo. El resumen del preview sí la nombra (R8). Decidir si debe
  ser interruptor a amarillo es una decisión de producto.
- **Pausa y «pending» de una suscripción se mapean igual** (PENDING): un webhook atrasado «pending» puede
  regresar una suscripción autorizada a pendiente. MP no distingue ambos casos en nuestro mapeo actual.
- **Prefijo «KL» de la tabla WMI** tiene 2 caracteres y nunca coincide con un WMI de 3; con sólo 2 entradas
  «KL*» tampoco aplica el respaldo por prefijo (V9). Efecto: marca desconocida, sin alarma.

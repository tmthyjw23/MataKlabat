# Analisis kegagalan

Dibuat 27-10-2026 14:05 WITA.

## Ringkasan metrik

| variant | n | errors | precision | recall | f1 | recall_any_alert | false_alarm_fog | false_alarm_sunset | false_alarm_lights | false_alarm_normal | lookalike_named_right | normal_called_lookalike | consistency | confidence_std_mean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| local | 12 | 0 | 0.333 | 1.0 | 0.5 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | - | - | - | - |
| v2 | 12 | 0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | 0.5 | 1.0 | 0.004 |

## F1 · Kabut/awan dikira asap (false positive)

- `fog/fog_01.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `fog/fog_02.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)

## F2 · Senja/lampu dikira api (false positive)

- `sunset/sunset_01.jpg` [local] → WASPADA (skor api 1.00, asap 0.00)
- `sunset/sunset_02.jpg` [local] → WASPADA (skor api 1.00, asap 0.00)
- `lights/lights_01.jpg` [local] → WASPADA (skor api 0.51, asap 0.23)
- `lights/lights_02.jpg` [local] → WASPADA (skor api 0.17, asap 0.06)

## F3 · Api/asap tidak terdeteksi (false negative)

Tidak ada contoh pada test set ini.

## Salah lainnya

- `normal/normal_01.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `normal/normal_02.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)

## F4 · Inkonsistensi LLM (--repeat)

Tidak ada (atau --repeat tidak dipakai).

## F5 · Pengaruh prompt (v1 vs v2)

Keputusan v1 dan v2 sama untuk semua gambar (atau hanya satu prompt diuji).

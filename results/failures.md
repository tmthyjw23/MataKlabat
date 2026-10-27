# Analisis kegagalan

Dibuat 27-10-2026 15:06 WITA.

## Ringkasan metrik

| variant | n | errors | precision | recall | f1 | recall_any_alert | false_alarm_fog | false_alarm_sunset | false_alarm_lights | false_alarm_normal | lookalike_named_right | normal_called_lookalike |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| local | 72 | 0 | 0.353 | 1.0 | 0.522 | 1.0 | 1.0 | 0.917 | 0.75 | 1.0 | - | - |
| v1 | 72 | 0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.889 | 0.583 |
| v2 | 72 | 0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | 1.0 |

## F1 · Kabut/awan dikira asap (false positive)

- `fog/fog_01.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `fog/fog_02.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `fog/fog_03.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `fog/fog_04.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `fog/fog_05.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `fog/fog_06.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `fog/fog_07.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `fog/fog_08.jpg` [local] → WASPADA (skor api 0.01, asap 1.00)
- `fog/fog_09.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `fog/fog_10.jpg` [local] → WASPADA (skor api 0.00, asap 0.83)
- `fog/fog_11.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `fog/fog_12.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)

## F2 · Senja/lampu dikira api (false positive)

- `sunset/sunset_01.jpg` [local] → WASPADA (skor api 1.00, asap 0.00)
- `sunset/sunset_02.jpg` [local] → WASPADA (skor api 1.00, asap 0.00)
- `sunset/sunset_04.jpg` [local] → WASPADA (skor api 0.99, asap 0.98)
- `sunset/sunset_05.jpg` [local] → WASPADA (skor api 1.00, asap 0.00)
- `sunset/sunset_06.jpg` [local] → WASPADA (skor api 1.00, asap 1.00)
- `sunset/sunset_07.jpg` [local] → WASPADA (skor api 1.00, asap 0.02)
- `sunset/sunset_08.jpg` [local] → WASPADA (skor api 1.00, asap 0.00)
- `sunset/sunset_09.jpg` [local] → WASPADA (skor api 1.00, asap 1.00)
- `sunset/sunset_10.jpg` [local] → WASPADA (skor api 0.67, asap 0.73)
- `sunset/sunset_11.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `sunset/sunset_12.jpg` [local] → WASPADA (skor api 1.00, asap 0.00)
- `lights/lights_01.jpg` [local] → WASPADA (skor api 0.51, asap 0.23)
- `lights/lights_02.jpg` [local] → WASPADA (skor api 0.17, asap 0.06)
- `lights/lights_03.jpg` [local] → WASPADA (skor api 0.17, asap 0.61)
- `lights/lights_06.jpg` [local] → WASPADA (skor api 0.28, asap 0.43)
- `lights/lights_08.jpg` [local] → WASPADA (skor api 0.05, asap 0.51)
- `lights/lights_09.jpg` [local] → WASPADA (skor api 0.74, asap 0.15)
- `lights/lights_10.jpg` [local] → WASPADA (skor api 1.00, asap 0.00)
- `lights/lights_11.jpg` [local] → WASPADA (skor api 0.01, asap 1.00)
- `lights/lights_12.jpg` [local] → WASPADA (skor api 0.03, asap 0.20)

## F3 · Api/asap tidak terdeteksi (false negative)

Tidak ada contoh pada test set ini.

## Salah lainnya

- `normal/normal_01.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `normal/normal_02.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `normal/normal_03.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `normal/normal_04.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `normal/normal_05.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `normal/normal_06.jpg` [local] → WASPADA (skor api 0.02, asap 0.60)
- `normal/normal_07.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `normal/normal_08.jpg` [local] → WASPADA (skor api 0.00, asap 0.59)
- `normal/normal_09.jpg` [local] → WASPADA (skor api 0.00, asap 0.77)
- `normal/normal_10.jpg` [local] → WASPADA (skor api 0.00, asap 1.00)
- `normal/normal_11.jpg` [local] → WASPADA (skor api 0.01, asap 1.00)
- `normal/normal_12.jpg` [local] → WASPADA (skor api 0.02, asap 0.99)

## F4 · Inkonsistensi LLM (--repeat)

Tidak ada (atau --repeat tidak dipakai).

## F5 · Pengaruh prompt (v1 vs v2)

Keputusan v1 dan v2 sama untuk semua gambar (atau hanya satu prompt diuji).

Perbedaan label lookalike (keputusan sama, cara model menamai berbeda):

- `fog/fog_02.jpg`: v1 `none` · v2 `fog_cloud`
- `sunset/sunset_07.jpg`: v1 `fog_cloud` · v2 `sunset_glare`
- `sunset/sunset_11.jpg`: v1 `none` · v2 `sunset_glare`
- `lights/lights_09.jpg`: v1 `sunset_glare` · v2 `artificial_light`
- `normal/normal_01.jpg`: v1 `none` · v2 `fog_cloud`
- `normal/normal_02.jpg`: v1 `none` · v2 `fog_cloud`
- `normal/normal_06.jpg`: v1 `none` · v2 `fog_cloud`
- `normal/normal_08.jpg`: v1 `none` · v2 `fog_cloud`
- `normal/normal_12.jpg`: v1 `none` · v2 `fog_cloud`

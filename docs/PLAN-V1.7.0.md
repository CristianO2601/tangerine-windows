# Plan v1.7.0 — Paridad visual y de funciones con Tangerine oficial

Estado: IMPLEMENTADO — v1.7.0 publicada (Olas A–D completadas) · Fuente: video promocional `tangerine-demo.mp4` (1316×1080 @60fps, 22.5 s) + texto de la web oficial + estado actual del repo (v1.6.0).
Objetivo: (1) replicar el HUD/animación y los paneles tal como se ven en el video, (2) añadir TODAS las funciones de la web que aún no tenemos, (3) ampliar con extras de calidad, (4) entregar v1.7.0 verificada (tests + build + PR + release).

---

## 1. Análisis del video (medido fotograma a fotograma)

### 1.1 Superficies = "material" translúcido (clave del look)
Las tres superficies del HUD (rueda, tarjeta de progreso, ventanas de editor) son **material translúcido estilo macOS**: dejan ver el fondo desenfocado con un lavado cálido claro. Evidencia: en la tarjeta "Crop Video" se transparenta un texto del escritorio; los pétalos inferiores de la rueda se ven rosados (fondo rosa) y los superiores crema (fondo naranja/amarillo).
Decisión de implementación: **captura del fondo + desenfoque + lavado** (no dependemos del blur del SO).
- Nuevo módulo `tangerine/hud.py`: captura la región de pantalla detrás de la superficie (`QScreen.grabWindow`), la desenfoca (downscale + GaussianBlur de Pillow), y la pinta recortada a un rect redondeado; encima, un lavado `wash` con alfa.
- Interfaz fija para todos los agentes:
```python
class HudBackdrop:
    def capture(self, global_rect: QRect) -> None      # una vez al mostrar; refresh en move (throttle 300ms)
    def paint(self, p: QPainter, rect: QRectF, wash: QColor, radius: float = 0.0) -> bool
    # True si pintó (captura disponible); False → fallback: solo wash
```
- Lavados (tema): claro `rgba(255,244,236,200)`, oscuro `rgba(30,25,22,195)`. Halo de la rueda: `rgba(125,110,100,90)` (gris translúcido, sin lavado blanco). Cápsula central: blanco `rgba(255,252,249,232)`.

### 1.2 Rueda (geometría medida, video → proporciones)
- R exterior pétalos ≈ 335 px, R interior ≈ 195, grosor ≈ 140 (0.42·R), hueco entre pétalos ≈ 8°, paso = 360/n.
- Halo (disco gris translúcido) hasta ≈ R+30 con borde difuso.
- Pétalos = **cuñas con esquinas redondeadas** (radio ≈ 0.28·grosor), no rectángulos. Nuestro truco de pintado: path de cuña (arco exterior + arco interior) pintado con pluma round-join ancha + relleno (redondea las esquinas convexas).
- **Modo conversión: el pétalo muestra SOLO el nombre del formato** (MP4/MKV/…) en mayúsculas, semibold, tracking ≈0.08 em, tamaño ≈0.076·R. SIN iconos.
- **Modo herramientas: icono de línea + etiqueta** en mayúsculas pequeña debajo. Iconos monocromos estilo SF Symbols (trazo 2 px, puntas redondas), color marrón oscuro `#3A2416`; NADA de emoji.
- **Hover**: pétalo a naranja plano `ACCENT` (#F87800; el video lo muestra más rojizo por la luz cálida de la escena), contenido sigue oscuro, transición ≈120 ms, ligero empuje hacia afuera (~4 px).
- **Centro (hub)**: sin texto fijo. Al hacer hover aparece una **cápsula horizontal** con el nombre del elemento señalado (p. ej. "SNAPSHOT" o "MKV"), blanco translúcido, texto oscuro bold con tracking; entra deslizándose desde el pétalo señalado (~140 ms, ease-out) y se desvanece al salir. (Elimina el actual "Convert/Tools + nombre de archivo" del centro.)
- **Aparición (t=1.40→1.55 s)**: pétalos salen del hub y se expanden: radio 0.6R→R con leve sobreimpulso, opacidad 0→1, retardo escalonado por pétalo ≈18 ms, labels funden con el pétalo; halo funde en 200 ms. Total ≈260 ms.
- **Despedida**: inverso rápido ≈160 ms (escala 0.94 + fade).
- Sonido de highlight se conserva.

### 1.3 Tarjeta de progreso
- Tarjeta translúcida clara, radio ≈28 px, sombra suave; fila superior: chip circular melocotón con ✕ + título bold **"Converting to MP4" / "Cropping video"**; debajo el nombre del archivo (regular); barra fina (≈10 px) con extremos redondeados: riel oscuro translúcido + relleno `ACCENT`. Sin texto de porcentaje ni botón Cancel visible (el ✕ cierra la tarjeta y el trabajo sigue — ya es nuestro comportamiento).
- Posición: cerca del cursor del drop, arriba o abajo según espacio (hoy: cascada centrada).

### 1.4 Ventanas de editor (p. ej. Crop Video)
- Tarjeta translúcida clara, radio ≈28 px; cabecera: chip ✕ a la izquierda + título bold centrado + hairline; cuerpo en una columna: preview, filas etiqueta+control; combo con stepper; **sliders con relleno naranja y thumb blanco redondo**; chips melocotón para acciones secundarias (Reset, play); botón **Apply** naranja con texto blanco abajo a la derecha; textos de tiempo en gris.
- Tema claro/oscuro conmutable: nuevo ajuste `appearanceTheme` = `system|light|dark` en Ajustes → General → Apariencia (el video es el tema claro; en oscuro se usa el mismo diseño con lavado oscuro).

### 1.5 Interacción
- El video: arrastrar con **Shift** = convertir; añadir **Option** = herramientas.
- La web añade: **Enter abre el menú de formato**; con Option cambia a herramientas; **flechas** eligen, **Enter** aplica, **Escape** cancela; en táctil: **mantener pulsado** un archivo y luego arrastrar.
- Implementación Windows: (a) flechas/Enter/Escape con la rueda visible (A2); (b) Enter+Shift con selección en Explorer → rueda en el cursor leyendo la selección del Explorador en primer plano (`Shell.Application` COM, nuevo `tangerine/selection.py`) (A3); (c) modo táctil opcional: si un arrastre de archivos dura ≥700 ms sin modificador → mostrar rueda (ajuste `touchLongPressEnabled`, por defecto OFF) (A3).

---

## 2. Matriz de huecos (web oficial vs. nuestra v1.6.0)

### 2.1 Formatos
| Familia | Web | Hoy | Falta |
|---|---|---|---|
| Imagen | JPG PNG WebP HEIC TIFF SVG AVIF BMP | JPG PNG WebP HEIC TIFF SVG BMP | **AVIF (leer+escribir; pillow-heif 1.7 lo soporta — verificado)** |
| Audio | MP3 M4A WAV FLAC OGG Opus AIFF WMA | MP3 M4A WAV FLAC | **OGG, Opus, AIFF, WMA** (ffmpeg: libvorbis/libopus/pcm/wmav2 — verificado) |
| Video | MP4 MOV MKV WebM AVI WMV GIF + MP3 | MP4 MOV MKV GIF + MP3/M4A | **WebM, AVI, WMV** como destino (y .wmv como origen) (libvpx/mpeg4/wmv2 — verificado) |
| PDF | → DOCX JPG PNG TXT | ✔ + extras (compresión, split, merge, QR, OCR) | — |
| Texto | TXT → PDF JPG PNG **SRT VTT** | PDF JPG PNG | **SRT, VTT** |
| Subtítulos | SRT VTT TXT | — | **Familia completa: srt↔vtt, →txt** |
| Archivos | ZIP TAR GZIP RAR | ✔ | — |
| Documentos | (no listados) | DOCX XLSX PPTX CSV RTF MD ODT EPUB | ya superamos |

### 2.2 Herramientas
| Herramienta web | Hoy | Falta |
|---|---|---|
| Comprimir imágenes (Balanced/Strong + resize) | ✔ | — |
| Editar metadatos (ubicación, cámara, autor) | parcial | **GPS/ubicación editable + "Quitar ubicación"** |
| Editar fotos (exposición, color, detalle, efectos) | básico (brillo/contraste/saturación/nitidez) | **exposición (gamma), temperatura, vibrance, viñeta, grano?, presets de efecto (Mono/Sepia/Noir/Vívido cálido/frío)** |
| Añadir fondo (color sólido, **degradado o imagen**; aspecto, espaciado, radio) | solo color + margen | **degradado, imagen, relación de aspecto, espaciado, radio** |
| Recortar imágenes | ✔ | — |
| Censurar fotos (sólido, blur **o pixelado**) | sólido/blur | **pixelado** |
| Crear PDF (multi) | ✔ | — |
| Collage (grid/fila/columna/featured) | ✔ | — |
| Herramientas de video (8: SPLIT COMPRESS REMOVE META SNAPSHOT SPEED MUTE TRIM CROP) | ✔ (+redact/join extra) | **pixelado en redact video** |
| Herramientas de audio | ✔ (compress/meta/normalize/visualizer/trim/channels/bleep) | — |

### 2.3 Extras nuestros más allá de la web (mantener y sumar)
- Extras actuales: OCR de PDFs, familia Documentos (8 formatos), compresión de PDF, split/merge PDF, QR, redact video, join, limpiar texto, compresión de documentos.
- Nuevos extras v1.7.0: **OCR sobre imágenes sueltas** (herramienta "Leer texto (OCR)" → TXT usando RapidOCR ya integrado), soporte de subtítulos con limpieza (espacios en blanco, BOM) y fechas.

---

## 3. Fases de implementación (olas secuenciales; paralelo dentro de cada ola)

### Ola A — Paridad visual del HUD (3 agentes en paralelo, archivos disjuntos)
- **A1 · Tema y superficie**: `theme.py` (tokens del material claro/oscuro, paleta HUD, QSS claro con sliders naranja+thumb blanco, chips, botones Apply), **nuevo `hud.py`** (HudBackdrop con la interfaz fija), `settings.py` (`appearanceTheme`, `touchLongPressEnabled`), `settings_window.py` (fila Apariencia), `progress.py` (tarjeta nueva).
- **A2 · Rueda**: `icons.py` → set de **iconos de línea vectoriales** (QPainterPath stroke 2 px) para ~40 herramientas, sin emoji; `wheel.py` reescritura: geometría de cuñas, halo, frosted, cápsula central con hover-label animada, animación de aparición/despedida escalonada, hover 120 ms, teclado (flechas/Enter/Escape), sin prompt central; `main.py` ajusta `_show_wheel` (sin `set_prompt`).
- **A3 · Editores y activación**: reestilo claro de `editors/*` (chips, combos, sliders, Apply, footers) usando tokens; **nuevo `selection.py`** (selección de Explorer vía Shell.Application) + `monitor.py`/`main.py`: trigger **Shift+Enter** con selección → rueda con teclado; modo táctil `touchLongPressEnabled`.
- Aceptación A: rueda renderizada ≈ referencia del video (formas/tokens/animación), tarjeta de progreso y editores claros, teclado operativo, tests de humo y auditoría en verde, capturas comparativas en `docs/preview/`.

### Ola B — Formatos (1 agente)
`catalog.py` (AVIF; OGG/Opus/AIFF/WMA; WebM/AVI/WMV; familia subtítulos SRT/VTT), `engines.py` (AVIF vía pillow-heif en `convert_image`; audio nuevos códecs; video targets nuevos con filtros even; `.wmv` origen; `convert_subtitle` srt↔vtt/txt con decodificación tolerante), `media.py` (detección), `tools.py` (audio_codec_args extendido), tests (`tests/test_formats_v17.py`), matriz de rutas actualizada.
Aceptación B: cada nuevo par origen→destino produce archivo válido (ffprobe/Pillow), auditoría de rutas ampliada verde.

### Ola C — Herramientas (1 agente)
`tools.py`: `pixelate` en `redact_photo`/`redact_video` (modo nuevo, bloque 12 px), `add_background` completo (color/degradado/imagen, aspecto, espaciado, radio esquinas), `edit_image` (exposición/contraste/saturación/temperatura/vibrance/nitidez/viñeta + presets), metadatos GPS (leer/escribir/quitar ubicación). `editors/images.py` + `ui/canvas.py` (controles nuevos), textos i18n.
Aceptación C: pruebas por pixel (pixelado rectangular uniforme, fondo con radio, GPS round-trip), diálogos de humo 23/23+.

### Ola D — Verificación y entrega
- Batería: `pytest` (ampliado), `audit_routing` (todas las rutas nuevas), `smoke_editors`, `verify_docs`, `e2e_tools` (+ casos nuevos), `check_compress_pdf`, captura visual de la rueda vs. referencia.
- Docs: README/INVENTARIO/CHANGELOG 1.7.0; bump `APP_VERSION` 1.7.0.
- Build: `packaging/build.ps1`; tag `v1.7.0`; PR(s) + release con Setup + portable (workflows CI siguen pendientes del permiso `workflow`).

---

## 4. Riesgos y mitigaciones
- **Captura de fondo**: DPI/multimonitor → usar el `QScreen` que contiene el rect y `devicePixelRatio`; fallback a solo-lavado si `grabWindow` falla.
- **Coste del blur**: región pequeña (rueda ~500 px) + Pillow; refresco con throttle; nunca en el hilo de pintado en cada frame (cachear).
- **Cambios de API de la rueda** (prompt central eliminado): actualizar pruebas temporales (`t3_verify_*`, `smoke_editors`) y cualquier referencia; los tests del repo no dependen del prompt.
- **Enter+Shift global**: leer la selección de Explorer puede bloquear si COM está ocupado → timeout corto + reintento en hilo, nunca en el GUI thread.
- **WebM/WMV**: velocidades distintas; usar preset muy rápido y límites, documentar.
- **Grados de libertad del video**: el color está teñido por la luz de la escena; se toman los valores medidos como referencia tonal, normalizados al `ACCENT` de marca.

## 5. Criterio de "terminado" v1.7.0
- HUD visualmente equivalente (capturas lado a lado), animación de aparición/despedida/hover/cápsula, sin emoji, con teclado.
- Todos los formatos de la web soportados + extras; todas las herramientas web implementadas + extras.
- Batería completa verde y binarios regenerados; release v1.7.0 publicado.

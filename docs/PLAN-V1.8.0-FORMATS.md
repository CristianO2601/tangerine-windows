# Plan v1.8.0 — Formatos, fidelidad de conversión y flujo de trabajo

Estado: EN CURSO — el **primer lote ya está implementado y verificado** (selección múltiple, rueda fija y scroll con la rueda; 144 pruebas en verde). El resto del documento es el roadmap acordado para completar la versión.
Fuentes: investigación de apps similares (FileConverter, Stirling PDF, PDF24, XnConvert, Shutter Encoder, ConvertX, VERT, BentoPDF), verificación de librerías en PyPI/GitHub (wheels Windows + Python 3.14), estado actual del repo y feedback del usuario.
Objetivo: (1) que ninguna conversión sea "superficial" — todo se renderiza de verdad; (2) cerrar los huecos de formatos con más demanda **sin dependencias externas** (nada de LibreOffice, Ghostscript ni Office); (3) llevar el flujo de trabajo al nivel de las mejores apps locales (presets, menú contextual, carpetas vigiladas, CLI) manteniendo la rueda como sello de identidad; (4) todo empaquetado y funcional en la app.

---

## 1. Primer lote implementado (este ciclo)

### 1.1 Selección múltiple — dos bugs reales corregidos
Diagnóstico confirmado por el usuario: (a) seleccionar archivos de **tipos distintos** (p. ej. foto + PDF + TXT) dejaba la rueda vacía; (b) arrastrar **varios archivos** con Shift convertía solo el primero.

- **Conversiones mixtas por intersección** (`catalog.py`): para familias mixtas se calculan los destinos válidos de cada familia y se ofrece la intersección, de modo que *todos* los archivos seleccionados se convierten con el mismo destino. Ejemplos reales: JPG+PDF → `PNG`, `DOCX`; JPG+TXT → `PNG`, `PDF`; PDF+TXT → `JPG`, `PNG`. Si no hay destino común, la rueda lo dice en vez de quedarse vacía.
- **Herramientas batch mixtas por unión** (`catalog.py`): con selección mixta se ofrecen solo las herramientas que aplican a subconjuntos (comprimir/reunir imágenes, unir PDFs, unir vídeos, comprimir audio, leer QR) con sus mínimos exigidos (p. ej. collage ≥2 imágenes, merge ≥2 PDFs).
- **`catalog.tool_paths(key, paths)`**: al activar una herramienta se filtran las rutas a las familias que esa herramienta entiende; el controlador ya no le pasa archivos que no sabe manejar (antes `img.compress` con un PDF incluido podía fallar).
- **Selección del Explorador como respaldo** (`monitor.py` + `wheel.py`): mientras no hay botón pulsado, el monitor guarda en segundo plano la selección real de la ventana de Explorador en primer plano (COM `Shell.Application`, mismo hilo de `selection.py`). Al mostrarse la rueda, si el portapapeles OLE trae `None` o un solo archivo pero hay un snapshot fresco (<4 s, misma ventana) con más, la rueda **hidrata** la lista completa. Además `dragEnterEvent` ya no deja que un payload colapsado pise una selección mayor conocida. Esto cubre la causa raíz: en Windows, mantener Shift antes/durante el clic muta la selección del Explorador y el arrastre acaba publicando un solo archivo.
- **Tests**: `tests/test_catalog_mixed.py` (9), `tests/test_monitor_snapshot.py` (5), `tests/test_wheel_pointer.py` (4). Suite total: **144 pruebas en verde**.

### 1.2 Rueda fija (sticky wheel) — caso "quiero tomar una captura"
- Nuevo atajo configurable (por defecto **Ctrl+Shift+W**) que abre la rueda con los archivos seleccionados en el Explorador y la mantiene abierta **aunque sueltes todo**.
- Interacción en modo fijo: **clic en un pétalo** aplica la acción, **clic fuera** cierra, **Escape** cierra, **rueda del ratón** (scroll) mueve el foco entre pétalos.
- El flujo clásico **no cambia**: Shift + arrastrar sigue mostrando la rueda y la oculta al soltar (la rueda fija es un ajuste aparte).
- Piezas: `settings.wheelToggleHotkey` (+`parse_hotkey`/`format_hotkey`/`hotkey_label`), controles en `settings_window.py` (`HotkeyEdit` que captura la combinación; borrar con Backspace/Delete la desactiva), señal `stickyTriggered` en `monitor.py`, señal `closed` y `mousePressEvent`/`wheelEvent` en `wheel.py`, textos EN/ES en `i18n.py`.
- **Scroll = barra extra**: se interpretó el pedido como navegación por scroll sobre la propia rueda; ya funciona. Un "riel" lateral desplazable para listas largas queda como propuesta de UI (§7.4) si la rueda crece con las herramientas nuevas.

---

## 2. Inspiración: qué copiamos de las apps líderes (y qué no)

| App | Qué adoptamos | Qué evitamos |
|---|---|---|
| **FileConverter** (15.2k★) | El menú contextual como segundo acceso, presets con **plantillas de nombre** (`(n:i)/(n:c)` para "página 1 de N", fecha, carpeta), carpeta de salida configurable, borrar original solo al éxito, máx. 2 trabajos simultáneos con progreso/ETA | Extensión shell frágil (su bug #1: el menú desaparece tras actualizar), instalador que exige admin y lo bloquea el antivirus |
| **Stirling PDF** (92.5k★) | Lista de paridad PDF priorizada por uso real: fusionar, dividir, comprimir, convertir, OCR, comparar, redactar | Rendering vía LibreOffice/Ghostscript (RECHAZADO: dependencia externa); sustitución de fuentes que rompe el layout |
| **PDF24** | Orden de popularidad como guía (Merge, Split, Compress, Edit, Sign, Create, Converter, Images→PDF) | — |
| **XnConvert / Shutter Encoder** | Presets compartibles, **carpetas vigiladas** (esperando tamaño estable), cola de trabajos, borrado del origen al terminar bien, passthrough de comandos | — |
| **ConvertX / VERT** | Checklist de huecos demandados: archivos (7z), DJVU, EPUB/AZW3, HEIC/AVIF/JXL, Office legacy | Su stack pesado (ImageMagick, LibreOffice, Calibre) |
| **BentoPDF** | El mensaje "100% local, nada se sube" como diferenciador (ya es nuestra naturaleza) | WebAssembly con requisitos de COOP/COEP |

**Conclusión de producto**: pocos presets pero profundos (~15 flujos curados, no cientos), plantillas de nombre desde el día uno, y la rueda + menú contextual como accesos gemelos.

---

## 3. Principio rector: render fiel, nunca conversión floja (P0)

Regla: **si convertimos, se ve bien**. Convertir Markdown a PDF mostrando `**negritas**` o un DOCX que pierde títulos, listas e imágenes no es una conversión: es un volcado de texto. Cada destino se implementa con el mejor motor posible **empaquetado en la app** y, cuando algo es aproximado por límites técnicos, se etiqueta honestamente en la UI.

### 3.1 Motor de render: QtWebEngine (ya viene con PySide6)

La app ya depende de PySide6; `QtWebEngineWidgets` es importable en esta máquina (verificado) y `QWebEnginePage.printToPdf()` produce PDF con CSS de impresión real (`@page`, saltos de página, tablas, flex/grid, fuentes, JS). No necesita red ni ningún binario externo; PyInstaller tiene hooks de primera clase. Coste: ~120–180 MB de DLLs/recursos en el bundle (licencia LGPL-3.0, compatible con el MIT del proyecto, sin modificar y reemplazable).

Pipeline maestro: **documento → HTML semántico + CSS de impresión → `printToPdf` → PDF**; el mismo HTML sirve para `→HTML`.

### 3.2 Matriz de fidelidad por conversión

| Conversión | Motor propuesto | Fidelidad | Notas |
|---|---|---|---|
| MD → HTML/PDF | `markdown-it-py` + `mdit-py-plugins` (tablas GFM, notas, tasklists) + `Pygments` + KaTeX (mate) + CSS GitHub | **Alta** (render real) | Mermaid opcional más adelante; nada de pandoc (GPL) |
| TXT → PDF | mismo pipeline (texto plano con monoespaciado/paginado) | Alta | Resuelve el "PDF que no respeta nada" |
| DOCX → HTML/PDF | `mammoth` → HTML semántico (títulos, listas, tablas, imágenes, notas, enlaces) + CSS de impresión | **Media-alta semántica** | Sin LibreOffice nadie reproduce columnas/cabeceras/pies al 100 %; se documenta en la UI |
| XLSX → PDF/HTML | `openpyxl` + `xlsx2html` (estilos, celdas combinadas, bordes) | Media-alta (tablas) | Gráficos de Excel no se pueden rasterizar offline; se avisa |
| PPTX → PDF | renderer propio con `python-pptx` + QPainter/ReportLab | Aproximada (~70–90 %) | Se pierde SmartArt/gráficos/temas; etiquetar "aproximado" o extraer texto+imágenes |
| PDF → imágenes | `pypdfium2` a 150–300 DPI | **Alta** | Ya usado en la app |
| PDF → TXT | `pdfminer.six` (+ RapidOCR si es escaneado) | Alta | OCR ya bundleado |
| PDF → DOCX | `pdfplumber`/`pdfminer.six` + `python-docx` (texto + tablas) | Media (sin layout) | `pdf2docx` queda descartado: depende de PyMuPDF (**AGPL**). Se etiqueta "texto y tablas" |
| PDF → HTML | `pypdfium2` render + capa de texto posicionada de `pdfminer.six` | **Visual 100 % + seleccionable** | Alternativa ética a pdf2htmlEX (GPL) |
| HTML/MD/EPUB → PDF | QtWebEngine `printToPdf` | Alta | EPUB: lectura con parser propio (zip+xhtml) |

### 3.3 Licencias — regla dura
El proyecto es **MIT**. No se empaquetan componentes **AGPL/GPL**: PyMuPDF (AGPL), Ghostscript (AGPL), pdf2htmlEX (GPL), ebooklib (AGPL), `mobi`/KindleUnpack (GPL), `piper1-gpl` (GPL-3.0), `extract-msg` (GPL), antiword (GPL). Sí se aceptan **LGPL/MPL/BSD/MIT** sin modificar y reemplazables: QtWebEngine (LGPL-3.0), `pikepdf` (MPL-2.0), `py7zr` (LGPL-2.1), LibRaw vía `rawpy` (LGPL-2.1/CDDL). Si el usuario tiene Ghostscript instalado, se puede **detectar y ofrecer** como extra opcional, nunca incluir.

---

## 4. Pack PDF completo (P1)

Hoy: convertir (docx/jpg/png/txt), comprimir suave, metadata, dividir, unir, QR, OCR. Objetivo: paridad con los líderes, todo offline.

| Operación | Implementación (MIT-safe) |
|---|---|
| Fusionar / dividir por rango o tamaño / extraer páginas | `pikepdf`/`pypdf` (ya en stack) |
| Rotar y **organizar con miniaturas** (borrar, reordenar, girar, duplicar) | `pikepdf` + `pypdfium2` para miniaturas |
| Comprimir **fuerte** (reducir resolución de imágenes incrustadas, recomprimir JPEG) | Iterar `PdfImage` de `pikepdf` → Pillow → reemplazar; presets (bajo/medio/fuerte) estilo PDF24 |
| Cifrar/descifrar AES-256 + permisos (imprimir/copiar) | `pikepdf` (`encryption`) |
| Marca de agua (texto/imagen, opacidad, ángulo) y **numeración de páginas** | `reportlab` (ya en stack) sobre las páginas |
| OCR searchable (PDF escaneado → capa de texto) | RapidOCR/onnxruntime (ya bundleado) |
| Firmar visualmente (imagen de firma + texto) | `reportlab`/`pypdf` |
| Metadatos, reparar, linearizar (apertura rápida web), flatten | `pikepdf` |
| PDF → Office/imágenes/texto/HTML | §3.2; DOCX honesto |
| Imágenes/MD/HTML/EPUB → PDF | QtWebEngine |
| Extraer tablas → CSV/XLSX | `pdfplumber` |
| Marcadores/TOC: leer y escribir | `pikepdf` |
| Comparar dos PDFs (visual/texto) | render + diff de texto `pdfminer` |
| N-up / folleto (2/4 páginas por hoja) | `pypdf` (transformaciones) + `reportlab` |

UI propuesta: nueva rueda de herramientas PDF por secciones (Organizar · Convertir · Seguridad · Optimizar), con vista previa de miniaturas para organizar. Todo con presets y plantillas de nombre.

---

## 5. Voz: TTS y STT 100 % offline (P2)

El bundle **ya incluye `onnxruntime`** (lo usa RapidOCR), así que los motores de voz no añaden runtime nuevo: solo modelos.

### 5.1 Texto → audio (TXT/MD/PDF/EPUB → MP3/M4B)
- **Kokoro-82M** (modelo Apache-2.0; `kokoro-onnx` MIT): 24 voces incluido **español** (`ef_dora`, `em_alex`, `em_santa`); calidad muy superior a Piper; fp16 ~169 MB / int8 ~88 MB + 27 MB de voces. Se integra vendorizando su pequeño código de inferencia (su metadata aún no declara Python 3.14).
- Fallback sin descargas: `pyttsx3`/SAPI de Windows (voces del sistema) para equipos sin modelo.
- **M4B con capítulos** por página/encabezado: FFmpeg (ya bundleado) muxea AAC + `FFMETADATA`.
- Flujo estrella: **escaneo → OCR (RapidOCR) → texto → audio**, todo local y en un solo drop.
- Eficiencia: síntesis por frases con cola en streaming a FFmpeg (memoria acotada), reanudable por capítulo.

### 5.2 Audio/vídeo → texto (MP3/M4A/MP4/MKV → TXT/SRT/VTT)
- **faster-whisper** (MIT) + `ctranslate2` (MIT, wheels cp314 ✓) — mejor precisión; alternativa simple `pywhispercpp` (MIT, 1 archivo DLL) para el preset "rápido".
- VAD **silero-vad** (MIT, ONNX 10.8 MB) para segmentar y acelerar.
- Modelos por tramos: tiny ~75 MB (rápido) / base ~145 MB (recomendado) / small ~480 MB (preciso), descargados la primera vez con consentimiento; el instalador queda liviano.
- Salidas: TXT con timestamps opcionales, SRT/VTT con marcas de hablante (experimental), traducción opcional más adelante.

---

## 6. Huecos de formatos con más demanda (P3)

| Hueco | Librería / medio | Licencia | Notas |
|---|---|---|---|
| **7z** (leer/escribir) | `py7zr` | LGPL-2.1 | + extracción de bz2/xz (stdlib) y `zstandard` (BSD-3) |
| **JPEG XL** (leer/escribir) | `pillow-jxl-plugin` | BSD-3 | libjxl empaquetada |
| **JPEG 2000** | Pillow (OpenJPEG) | BSD | ya soportado por Pillow |
| **PSD** | `psd-tools` | MIT | plano compuesto → PNG |
| **RAW** (CR2/NEF/ARW…) | `rawpy` (LibRaw) | MIT/LGPL | revelado básico |
| **ICO** | Pillow | — | leer/escribir |
| **WavPack / ALAC / APE** | FFmpeg | LGPL | APE solo decodificación (no existe encoder en FFmpeg) |
| **MP3 bitrate configurable** | FFmpeg | LGPL | pedido histórico de ConvertX (#595): presets 128/192/320/V0 |
| **EPUB** (crear) | propio (`zipfile` + XHTML3) | — | `ebooklib` es AGPL: se implementa un escritor mínimo |
| **DOC/XLS legacy** | texto: parser propio/`xlrd` | BSD | honesto: sin Office no hay render fiel de `.doc`; `.xls` valores sí |
| **MSG/EML** | `msg-parser` / stdlib | BSD | correo → PDF/HTML/TXT |
| **JSON/XML/YAML/CSV** | stdlib + `PyYAML`/`lxml` | MIT/BSD | conversiones entre sí y a tablas |
| **Detección de tipo real** | `puremagic` + `filetype` + inspección ZIP | MIT | enruta aunque la extensión mienta |

Regla: cada formato nuevo entra con test de ida y vuelta y aparece en la rueda automáticamente vía `catalog.py`.

---

## 7. Flujo de trabajo e integración con Windows (P4)

### 7.1 Menú contextual (clic derecho)
Segundo acceso además de la rueda, al estilo FileConverter pero con sus lecciones aprendidas: instalación **por usuario** (sin admin/AV), autorreparación si Windows lo desactiva tras actualizar (su bug crónico), y en Windows 11 aceptar vivir en "Mostrar más opciones" o registrarse con el nuevo `IExplorerCommand`. Los presets se organizan en carpetas-submenú.

### 7.2 Presets y plantillas de nombre
- Preset = formato/salida + carpeta de destino + plantilla de nombre + calidad + posacción (borrar original, copiar ruta, abrir).
- Plantillas con tokens al estilo FileConverter: `{name}`, `{ext}`, `{date}`, `{n:i}`/`{n:c}` ("página 1 de N"), carpeta padre. Valores por defecto sanos: misma carpeta, mismo nombre, nueva extensión.
- Importar/exportar presets (JSON) y reordenar por arrastre. ~15 presets curados de fábrica.

### 7.3 Cola, progreso y carpetas vigiladas
- Máximo 2 trabajos simultáneos, progreso + ETA en la tarjeta y barra de tareas, resumen al terminar, borrar origen solo si todo fue bien.
- **Carpetas vigiladas**: detectar archivos nuevos esperando a que el tamaño se estabilice (patrón Shutter) y aplicar un preset. Ideal para "escanear → PDF buscable" o "descarga → MP4".

### 7.4 Accesos adicionales
- **SendTo** ("Enviar a → Tangerine") con preset por defecto.
- **CLI headless**: `Tangerine.exe --convert archivo --to pdf --out carpeta --preset X` (útil para scripts, PowerToys Command Palette, MCP).
- **"Barra extra con scroll"**: ya implementado el scroll sobre la rueda; si las herramientas crecen, un riel desplazable de pétalos/listas (estilo XnConvert) es la extensión natural.

### 7.5 Honestidad de producto
Cada diálogo/conversión indica su nivel de fidelidad: "render completo" (MD/HTML), "semántico" (DOCX/XLSX), "aproximado" (PPTX). Mejor avisar que decepcionar.

---

## 8. Fases, tamaño y criterios de aceptación

| Fase | Contenido | Coste de bundle (aprox.) | Estado |
|---|---|---|---|
| **Lote 0** | Multi-archivo (intersección + snapshot + merge), rueda fija, scroll en la rueda | 0 MB | **Implementado — 144 tests** |
| **P0** | Motor QtWebEngine + MD/TXT/DOCX/XLSX con render fiel + PDF→HTML/DOCX honesto | +120–180 MB | Propuesto |
| **P1** | Pack PDF completo (§4) | +5–8 MB | Propuesto |
| **P2** | TTS Kokoro + STT faster-whisper + M4B/SRT | +20 MB código; modelos 88–480 MB bajo demanda | Propuesto |
| **P3** | Huecos de formatos (§6) | +8–12 MB | Propuesto |
| **P4** | Menú contextual, SendTo, CLI, carpetas vigiladas, presets | +2 MB | Propuesto |

Criterios de aceptación por fase:
1. **Cero dependencias externas**: todo funciona en una máquina sin Office ni LibreOffice ni Ghostscript.
2. **Fidelidad verificable**: cada conversión nueva tiene test con archivo real (fixtures como en `tests/test_formats_v17.py`) y comparación visual mínima (tamaño de página, texto extraíble, imágenes presentes).
3. **Sin regresiones**: la suite completa (144+) sigue verde y el instalador no crece más de lo presupuestado (objetivo < ~350 MB).
4. **Licencias revisadas**: ninguna dependencia AGPL/GPL en el bundle distribuido.
5. **Rendimiento**: conversión típica de 1 página < 5 s en CPU; TTS al menos más rápido que tiempo real con Kokoro int8.

## 9. Riesgos y decisiones abiertas
- **Tamaño**: QtWebEngine engorda el instalador (~2×). Alternativa ligera: WeasyPrint (necesita Pango/GTK, también pesado) — se mantiene QtWebEngine por fidelidad y por ser ya dependencia.
- **Modelos de voz**: ¿descarga bajo demanda en primera ejecución (consentimiento) o "modo completo" opcional en el instalador? Propuesta: descarga guiada, con opción offline total vía paquete extra.
- **PPTX**: render aproximado; la alternativa fiel exigiría Office o LibreOffice (descartado).
- **Fuentes**: sustituir Calibri/Aptos por fuentes libres métricamente compatibles (Carlito) para que el render no baile; empaquetar un set mínimo.
- **DOCX PDF→DOCX fiel**: imposible sin AGPL; se ofrece "texto + tablas" y se etiqueta.

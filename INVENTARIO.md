# Inventario de funciones — Tangerine para Windows

Versión **1.9.0**. Estado verificado: auditoría de rutas **43/43 OK**, suite completa **165 pruebas (164 verdes, 1 omitida por diseño)**, smoke de editores **23/23**, regresión de arrastre **11/11**, extremo a extremo **50/50**, rutas de documentos **38/38**.

## Cómo funciona

1. Arrastra uno o más archivos desde el Explorador manteniendo **Shift** para convertir formatos.
2. Mantén **Alt+Shift** al arrastrar para abrir las herramientas de archivo.
3. La rueda aparece bajo el cursor y se queda fija; mueve el cursor a un pétalo y suelta.
4. El original **nunca** se toca: todo se guarda como copia con nombre nuevo en la misma carpeta.

Con la rueda visible el teclado funciona: **←/↑** y **→/↓** recorren los pétalos (con vuelta circular), **Enter** aplica y **Escape** cancela. En el Explorador, **Shift+Enter** con archivos seleccionados abre la rueda en el cursor para esa selección. El **modo táctil** opcional (`touchLongPressEnabled`, desactivado por defecto) muestra la rueda al mantener pulsado un arrastre ≥700 ms sin modificadores.

## Interfaz y apariencia (HUD)

Las tres superficies del HUD (rueda, tarjeta de progreso y ventanas de editor) son **material translúcido**: Tangerine captura el escritorio tras la ventana, lo desenfoca y lo lava con un tinte cálido, sin depender del desenfoque del sistema (si la captura falla, queda solo el lavado).

- **Rueda:** pétalos en cuña con esquinas redondeadas y halo; en conversión cada pétalo muestra solo su etiqueta grande en mayúsculas (sin iconos), en herramientas un icono de línea monocromo con etiqueta. El pétalo señalado pasa a naranja (~120 ms) y una cápsula central entra deslizándose con el nombre del elemento. Aparición escalonada (~250 ms) y despedida rápida (~160 ms).
- **Tarjeta de progreso:** chip de cierre melocotón, título en negrita («Converting to MP4», «Cropping video»…), nombre del archivo y barra fina naranja.
- **Ventanas de editor:** cabecera propia con chip de cierre, título centrado y línea fina; sliders naranja con thumb blanco, chips melocotón y botón **Apply** naranja.
- **Apariencia:** **Ajustes → General → Apariencia** = **Sistema / Claro / Oscuro** (ajuste `appearanceTheme`, cambio en vivo).
- **Sonido:** se conserva el sonido de highlight.

## Conversiones (Shift)

| Familia | Formatos de salida |
| --- | --- |
| Imagen (jpg, png, webp, avif, tiff, heic, bmp, svg…) | jpg, png, webp, avif, heic, tiff, pdf, docx* |
| Audio (mp3, m4a, wav, flac, ogg, opus, aiff, wma) | mp3, m4a, wav, flac, ogg, opus, aiff, wma |
| Vídeo (mp4, mov, mkv, avi, webm, wmv, m4v) | mp4, mov, mkv, webm, avi, wmv, gif, mp3, m4a |
| GIF | mp4, mov, mkv, webm, avi, wmv |
| Subtítulos (srt, vtt) | srt ↔ vtt y txt |
| PDF | docx, jpg, png, txt |
| TXT | pdf, jpg, png |
| Archivos (zip, tar, gz, rar) | zip, tar, gz, rar |

\* docx solo desde jpg/png. Varios archivos se convierten en lote; varios PDF se unen y varias imágenes se convierten a PDF o collage.

Los subtítulos no necesitan motor externo: la codificación se detecta de forma tolerante (BOM, UTF-8, CP1252), la salida es siempre UTF-8 y SRT↔VTT conserva texto y tiempos; TXT guarda solo el transcript.

**OCR opcional:** los PDF escaneados (sin capa de texto) se leen con `rapidocr-onnxruntime` (`pip install -r requirements-ocr.txt`) para las salidas txt/docx; sin el motor, el error indica el comando de instalación y docx→imagen sigue disponible.

## Documentos (Shift)

| Origen | Salidas |
| --- | --- |
| docx | txt, pdf, jpg, png |
| xlsx | csv, pdf, jpg, png |
| pptx | txt, pdf, jpg, png |
| csv | xlsx, pdf, jpg, png, txt |
| rtf | txt, pdf, jpg, png |
| md | txt, html, pdf, jpg, png |
| odt | txt, pdf, jpg, png |
| epub | txt |

Las salidas **pdf/jpg/png** de docx, xlsx, csv, md, rtf, odt y pptx se renderizan como HTML/CSS (QtWebEngine) y se imprimen con las opciones de **Ajustes → Formatos → Documentos y PDF**: papel A4 o Carta, márgenes normales/compactos/amplios y numeración de páginas opcional; el PDF resultante lleva título y metadatos de Tangerine. Las salidas jpg/png pasan por el mismo PDF intermedio a 300 ppp.

La herramienta **doc.compress** (Alt+Shift) recomprime el contenedor ZIP de docx, xlsx y pptx; si el resultado no queda más pequeño, conserva una copia del original.

**Nota honesta:** Markdown, DOCX, XLSX y CSV se renderizan como HTML/CSS (títulos, tablas, código y las imágenes de DOCX incluidas) y se imprimen a PDF con papel, márgenes y numeración configurables; TXT, RTF y ODT salen como párrafos legibles, y PPTX como una página por diapositiva con maquetación **aproximada** (sin animaciones ni posición exacta de formas). xlsx lee solo la hoja activa (valores en caché); doc→jpg/png se renderiza mediante un PDF intermedio a 300 ppp. Los formatos binarios antiguos (.doc/.xls/.ppt) no son compatibles: solo OOXML/ODF/texto.

## Herramientas (Alt+Shift)

**Imagen**: Comprimir · Metadatos (ver/editar/quitar ubicación GPS) · Editar foto (exposición, contraste, saturación, temperatura, vibrance, nitidez, viñeta, grano + presets Mono/Sepia/Noir/Vívido/Cálido/Frío) · Anotar · Añadir fondo (color, degradado con ángulo o imagen; relación de aspecto, margen, radio de esquinas) · Recortar · Censurar (sólido, desenfoque o pixelado 12 px, con detección de caras) · Crear PDF · Collage · Leer códigos QR

**Audio**: Comprimir · Metadatos · Normalizar volumen · Visualizador · Recortar · Canales (mono/estéreo) · Silenciar (bleep)

**Vídeo**: Comprimir · Metadatos · Quitar audio · Recortar · Recortar área · Velocidad · Capturas · Dividir · Censurar (sólido, desenfoque o pixelado) · Unir

**PDF**: Comprimir · Metadatos · Dividir · Leer códigos QR · Unir

**GIF**: Metadatos · Leer códigos QR

**TXT**: Limpiar texto

**Documentos**: Comprimir (doc.compress — docx, xlsx, pptx)

**Archivos**: Extraer (zip, tar, gz, rar)

## Idioma (i18n)

Interfaz en **inglés** y **español** (492 claves por idioma) elegible en **Ajustes → General → Idioma**; la opción **Sistema** sigue el idioma de Windows (`es_MX` → español) y recurre al inglés si no está soportado. El cambio se aplica al instante en la bandeja (menú y tooltip) y en la rueda; las ventanas ya abiertas lo aplican al reabrirse. Cobertura: rueda de conversiones y herramientas, bandeja, ajustes, los 20 diálogos de editor, ventanas de progreso y los errores comunes de motores/herramientas (los nombres de archivo, códigos y rutas no se traducen).

## Verificación

- Suite completa: **165 pruebas (164 verdes, 1 omitida por diseño)**, incluida paridad i18n en/es, formatos v1.7.0 (AVIF, audio, vídeo, subtítulos), pixelado, fondo completo, edición de foto, GPS, teclado de la rueda, memoria de lienzos y el pipeline de impresión v1.9.0 (papel, márgenes, numeración, metadatos y render HTML de TXT/RTF/ODT/PPTX).
- Render real comprobado (pypdfium2): PDF A4 de 595 × 842 pt desde Markdown, tinta a 44 pt (16 mm) del borde, «2 / 2» al pie y metadatos «Tangerine 1.9.0».
- Auditoría de rutas: las **43/43** herramientas abren su editor o ejecutan su proceso, sin mensajes de "no disponible".
- Smoke de editores: **23/23** diálogos se construyen en modo offscreen.
- Regresión del arrastre: **11/11** — soltar fuerza siempre una **copia** y rechaza orígenes que solo permiten mover.
- Extremo a extremo: **50/50** conversiones y herramientas comprobadas de principio a fin.
- Rutas de documentos: **38/38** con salidas válidas.
- Comprimir PDF verificado: notas.pdf 1 580 → 1 154 B; PDF de 30 páginas 27 956 → 27 408 B.
- Revisión de calidad y estabilidad (1.4.1): corregidos todos los hallazgos bloqueantes e importantes — seguridad al crear RAR, fotos rotadas (EXIF) en recorte/censura, censura de vídeo verificada, fusión de PDFs sin sobrescritura, cancelación real con limpieza, guardado atómico de ajustes, instancia única, y mejoras de memoria y rendimiento. Detalles en `CHANGELOG.md`.

## Novedades de esta versión (1.9.0)

La 1.8.0 ya había traído el render fiel de DOCX/XLSX/CSV/Markdown, la selección múltiple real de tipos mixtos y la rueda fija con `Ctrl+Shift+W`; esta versión pule la impresión y la extiende a más formatos.

- **Impresión:** papel A4/Carta, márgenes normales (16/18 mm), compactos (10/12 mm) o amplios (25/20 mm) y numeración de páginas opcional en **Ajustes → Formatos → Documentos y PDF**; se aplican a todas las salidas PDF/JPG/PNG de documentos.
- **PDF con oficio:** numeración «1 / 3» al pie y metadatos (Título, Autor, Creador, Productor) en cada PDF generado.
- **Más formatos por el pipeline HTML:** TXT (antes Courier 54 pt), RTF, ODT y PPTX (una página por diapositiva) se componen como HTML/CSS.
- **Tipografía de impresión:** títulos sin cortes, filas de tabla enteras, cabecera repetida, viudas/huérfanas controladas y `@media screen` para que el HTML exportado también se lea en pantalla.
- **Verificación:** 165 pruebas y comprobación real con pypdfium2 (A4, márgenes de 16 mm, numeración y metadatos).

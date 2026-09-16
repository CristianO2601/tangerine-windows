# Inventario de funciones — Tangerine para Windows

Estado verificado: auditoría de rutas **43/43 OK**, suite completa **85/85**, smoke de editores **23/23**, regresión de arrastre **11/11**.

## Cómo funciona

1. Arrastra uno o más archivos desde el Explorador manteniendo **Shift** para convertir formatos.
2. Mantén **Alt+Shift** al arrastrar para abrir las herramientas de archivo.
3. La rueda aparece bajo el cursor y se queda fija; mueve el cursor a un pétalo y suelta.
4. El original **nunca** se toca: todo se guarda como copia con nombre nuevo en la misma carpeta.

## Conversiones (Shift)

| Familia | Formatos de salida |
| --- | --- |
| Imagen (jpg, png, webp, tiff, heic, bmp, svg…) | jpg, png, webp, heic, tiff, pdf, docx* |
| Audio (mp3, m4a, wav, flac) | mp3, m4a, wav, flac |
| Vídeo (mp4, mov, mkv, avi, webm, m4v) | mp4, mov, mkv, gif, mp3, m4a |
| GIF | mp4, mov, mkv |
| PDF | docx, jpg, png, txt |
| TXT | pdf, jpg, png |
| Archivos (zip, tar, gz, rar) | zip, tar, gz, rar |

\* docx solo desde jpg/png. Varios archivos se convierten en lote; varios PDF se unen y varias imágenes se convierten a PDF o collage.

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

La herramienta **doc.compress** (Alt+Shift) recomprime el contenedor ZIP de docx, xlsx y pptx; si el resultado no queda más pequeño, conserva una copia del original.

**Nota honesta:** las conversiones de documentos trabajan a nivel de texto. docx→pdf y pptx→pdf conservan estilos básicos (las tablas van como filas de texto) y no reproducen imágenes, formas, gráficos ni fidelidad de maquetación compleja; xlsx lee solo la hoja activa (valores en caché); doc→jpg/png se renderiza mediante un PDF intermedio a 300 ppp. Los formatos binarios antiguos (.doc/.xls/.ppt) no son compatibles: solo OOXML/ODF/texto.

## Herramientas (Alt+Shift)

**Imagen**: Comprimir · Metadatos · Editar foto · Anotar · Añadir fondo · Recortar · Censurar (con detección de caras) · Crear PDF · Collage · Leer códigos QR

**Audio**: Comprimir · Metadatos · Normalizar volumen · Visualizador · Recortar · Canales (mono/estéreo) · Silenciar (bleep)

**Vídeo**: Comprimir · Metadatos · Quitar audio · Recortar · Recortar área · Velocidad · Capturas · Dividir · Censurar · Unir

**PDF**: Comprimir · Metadatos · Dividir · Leer códigos QR · Unir

**GIF**: Metadatos · Leer códigos QR

**TXT**: Limpiar texto

**Documentos**: Comprimir (doc.compress — docx, xlsx, pptx)

**Archivos**: Extraer (zip, tar, gz, rar)

## Idioma (i18n)

Interfaz en **inglés** y **español** (431 claves por idioma) elegible en **Ajustes → General → Idioma**; la opción **Sistema** sigue el idioma de Windows (`es_MX` → español) y recurre al inglés si no está soportado. El cambio se aplica al instante en la bandeja (menú y tooltip) y en la rueda; las ventanas ya abiertas lo aplican al reabrirse. Cobertura: rueda de conversiones y herramientas, bandeja, ajustes, los 20 diálogos de editor, ventanas de progreso y los errores comunes de motores/herramientas (los nombres de archivo, códigos y rutas no se traducen).

## Verificación

- Auditoría de rutas: las 43 herramientas abren su editor o ejecutan su proceso, sin mensajes de "no disponible".
- Suite completa: **85/85** pruebas (incluye paridad i18n en/es, OCR, memoria de lienzos y visualizador).
- Regresión del arrastre: 11/11 — soltar fuerza siempre una **copia** y rechaza orígenes que solo permiten mover.
- Comprimir PDF verificado: notas.pdf 1 580 → 1 154 B; PDF de 30 páginas 27 956 → 27 408 B.
- Revisión de calidad y estabilidad (1.4.1): corregidos todos los hallazgos bloqueantes e importantes — seguridad al crear RAR, fotos rotadas (EXIF) en recorte/censura, censura de vídeo verificada, fusión de PDFs sin sobrescritura, cancelación real con limpieza, guardado atómico de ajustes, instancia única, y mejoras de memoria y rendimiento. Detalles en `CHANGELOG.md`.

## Novedades de esta versión (1.6.0)

- **Idiomas:** interfaz completa en inglés y español (Ajustes → General → Idioma; opción Sistema), con cambio inmediato en bandeja y rueda.
- **OCR opcional** para PDF escaneados (`requirements-ocr.txt`): txt/docx recuperan el texto; sin el motor, el error indica cómo instalarlo.
- **Correcciones:** los lienzos de foto ya no retienen la imagen a resolución completa y el recorte exporta de nuevo a resolución completa.
- **Vídeo:** el visualizador incluye audio y avisa claramente si la fuente no tiene pista de audio.
- **Empaquetado:** script `packaging\build.ps1` (PyInstaller + ZIP portátil + instalador Inno Setup), spec, instalador y flujo de compilación.

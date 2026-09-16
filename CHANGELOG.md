# Changelog

## 1.5.0 — 2026-09-16

Nueva familia **Documentos** en la rueda de conversiones: ocho formatos (docx,
xlsx, pptx, csv, rtf, md, odt y epub) con sus rutas de salida, y la herramienta
**doc.compress** para recomprimir contenedores de Office.

### Documentos
- Conversiones: docx→txt/pdf/jpg/png; xlsx→csv/pdf/jpg/png;
  pptx→txt/pdf/jpg/png; csv→xlsx/pdf/jpg/png/txt; rtf→txt/pdf/jpg/png;
  md→txt/html/pdf/jpg/png; odt→txt/pdf/jpg/png; epub→txt.
- `doc.compress` (Alt+Shift): recomprime el ZIP interno de docx/xlsx/pptx a
  deflate máximo; si el resultado no es más pequeño, conserva el original.
- Dependencias nuevas: openpyxl, python-pptx, striprtf, odfpy y Markdown.

### Limitaciones honestas
- docx→pdf y pptx→pdf son a nivel de texto: estilos básicos y tablas como
  filas de texto; sin imágenes, formas, gráficos ni fidelidad de maquetación
  compleja.
- xlsx lee solo la hoja activa (valores en caché); doc→jpg/png se renderiza a
  través de un PDF intermedio a 300 ppp.
- Sin soporte de formatos binarios antiguos (.doc/.xls/.ppt): solo
  OOXML/ODF/texto (.docx/.xlsx/.pptx/.odt/.rtf/.md/.csv/.epub).

### Verificación (todos en verde)
- 33 pruebas de documentos: 31 rutas (origen → destino) ofrecidas por el
  catálogo y ejecutadas de extremo a extremo, `doc.compress` que nunca crece y
  error amigable ante un .docx corrupto. Suite completa: 60/60.

## 1.4.1 — 2026-09-16

Revisión de calidad y estabilidad ("code review hardening") aplicando las guías
addyosmani/agent-skills (code-review-and-quality) y awesome-skills
(code-review-skill): corrección, seguridad, arquitectura, rendimiento y
legibilidad. Todos los hallazgos bloqueantes e importantes fueron corregidos y
verificados.

### Seguridad
- Compresión de archivos: saneados los nombres de miembros que empiezan con
  `-`/`@` al crear RAR (evita inyección de argumentos en WinRAR).
- Extracción de `gz`: ahora por streaming (antes cargaba todo en RAM) con
  límite de tamaño; zip/tar con `filter="data"` y tope de 16 GB.
- Guardas para PDFs cifrados: mensaje claro "Password-protected PDFs are not
  supported" en lugar del confuso aviso de OCR.
- Ajuste de ventana (settings) con escritura atómica (`.json.tmp` + `os.replace`)
  y respaldo `.bak` si el JSON se corrompe; mutación bajo lock.

### Corrección
- EXIF: las imágenes rotadas (orientación 2-8) ya no se rotan dos veces al
  convertir JPEG/TIFF/WebP ni se exportan de lado a PDF/Word; los lienzos de
  Recortar/Censurar/Anotar y la detección de rostros trabajan en el espacio
  rotado correcto.
- Censurar video: las cajas inválidas ya no se ignoran en silencio; se avisa y
  se cancela con error si no queda ninguna válida (antes podía exportarse el
  video sin censurar).
- Fusionar PDFs ya no puede sobrescribir un "Merged PDF.pdf" anterior (colisión
  de nombres corregida).
- Conversiones fallidas o canceladas limpian archivos parciales (ffmpeg,
  archivos comprimidos) y ya no reportan éxito al cancelar.
- Dimensiones impares: se normalizan a pares en codificaciones x264 y en
  recortes de video (antes fallaba "width not divisible by 2").
- Velocidad de audio: guarda contra factor 0 (bucle infinito).
- Visualizador: las pistas de audio con audio de entrada ahora incluyen sonido.
- Metadatos: se conservan los metadatos EXIF de cámara completos (sub-IFD) al
  guardar copia, incluidos DateTimeOriginal, FNumber, ISO, LensModel.

### Estabilidad
- Cancelación real de trabajos (botón Cancel en la ventana de progreso) con
  limpieza de salidas y sin falsos "completado".
- Al salir con trabajos en curso se pide confirmación y se cancelan.
- Fin del bloqueo del hilo de UI por consultas al portapapeles/COM durante el
  arrastre; los análisis pesados (ondas de audio, fotogramas, caras) se
  difieren y muestran "Loading…".
- Miniaturas en collage para la vista previa (ya no reconstruye el collage
  completo en cada cambio).
- Ventanas de progreso ancladas (no pueden desaparecer por el recolector de
  basura) y no reaparecen si el usuario las cerró.
- Arranque único (lock) — una segunda instancia avisa y se cierra.
- Errores invisibles bajo `pythonw` ahora se registran en
  `%APPDATA%\Tangerine\crash.log` + `tangerine.log` (excepthook global).
- Ajustes de atajos del anillo: coincidencia por subconjunto (Shift+Ctrl ya no
  suprime la rueda), tecla Win derecha soportada, y el cambio de modo a mitad
  de arrastre reconstruye la rueda.

### Rendimiento
- Detección de motores memoizada y precalentada al inicio (antes ~550 ms en el
  primer arrastre).
- Copias de archivos sin recompresión con `copy2` (antes leían todo en RAM).
- `compress_image` reutiliza buffers y evita trabajo innecesario.
- Metadatos/ffprobe con menos bloqueos; cola de errores de ffmpeg para
  mensajes de fallo útiles.

### Verificación (todas en verde)
- 43/43 identificadores de herramientas enrutados (auditoría de rutas).
- 11/11 pruebas de regresión de arrastre (copiar, no mover).
- 50/50 pruebas extremo a extremo (conversiones + herramientas).
- Compresión de PDF: notes.pdf 1580 → 1154 B; PDF 30 páginas 27956 → 27408 B.

### Pendiente (roadmap)
- Dividir `editors.py` (2577 líneas) en paquete `editors/`.
- Reducir memoria de lienzos (pixmap de pantalla en lugar de resolución total).
- Unificar lógica duplicada de diálogos (ColorButton, run_and_close).
- Separar iconos y pintado de `wheel.py`.
- Visualizador para fuentes solo-video.

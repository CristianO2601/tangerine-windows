# Tangerine 1.10.0: imágenes a PDF

## Resultado y alcance

La conversión pertenece a Tangerine: un motor, un editor Qt, una tarjeta de
progreso y una instancia por usuario. No necesita Python, Tkinter ni una segunda
aplicación en el equipo de destino. La integración anterior independiente se
retira del registro únicamente si sus marcas de propiedad coinciden; sus
archivos se conservan y se guarda un respaldo JSON del registro.

La captura aportada por Cris demuestra que la entrada anterior no aparecía.
Crear un menú con una API auxiliar no prueba que Explorer lo muestre. El motivo
exacto de esa omisión sigue sin demostrarse: las políticas inspeccionadas no
exigen aprobación de extensiones y el CLSID anterior no está bloqueado. No se
atribuye el fallo a caché, arquitectura o permisos sin evidencia adicional.

## Entradas y flujo compartido

| Entrada | Comportamiento |
| --- | --- |
| Bandeja → Crear PDF con imágenes | Selector de imágenes y editor |
| Ajustes → General → Explorador de archivos | Editor y reparación del registro |
| Rueda de herramientas → Crear PDF | Editor con la selección actual |
| Rueda de conversiones → PDF, selección de imágenes | Un PDF combinado mediante el mismo editor |
| Clic derecho → Enviar a → Tangerine - Crear PDF | Editor con todos los argumentos recibidos |
| Clic derecho → Enviar a → Tangerine - PDF por nombre | Conversión rápida en orden natural |
| Submenú clásico Tangerine — PDF | Nombre natural, orden recibido o configuración manual |

```mermaid
flowchart LR
    Shell[Explorer / Enviar a] --> CLI[Tangerine.exe]
    CLI --> IPC[Canal local por usuario]
    IPC --> C[Controller]
    Wheel[Ruedas / bandeja / ajustes] --> C
    C --> Editor[Editor Qt compartido]
    C --> Quick[Acción rápida]
    Editor --> Job[Job + ProgressWindow]
    Quick --> Job
    Job --> Engine[Motor de imágenes existente + PdfOptions]
    Engine --> PDF[PDF nuevo junto a las imágenes]
```

El ejecutable secundario entrega la petición a la instancia abierta y termina.
El manejador nativo recibe toda la selección por `CF_HDROP` y escribe un
manifiesto UTF-8; no decodifica imágenes dentro de Explorer. La lista está
limitada a 10 000 rutas y menos de 8 MiB. El canal local valida el mensaje,
limita su tamaño, confirma recepción y evita procesar dos veces el mismo ID.

`Enviar a` proporciona una entrada mediante un menú que ya existe en Explorer.
La fila nativa de primer nivel requiere además que Explorer cargue la extensión.
Las pruebas del DLL y del registro no equivalen a una observación del menú real.
La integración no reinicia Explorer ni cambia sus políticas globales.

## Orden, salida y errores

- Nombre natural: Página 1, Página 2, Página 10.
- Orden recibido: conserva la lista entregada por Windows. No se promete la
  cronología de Ctrl+clic; el orden exacto se puede fijar en Manual.
- Una imagen por página por defecto; cuadrícula por filas y columnas opcional.
- Nombres de archivo opcionales en una banda blanca, con escala del texto.
- Rotación EXIF y transparencia a fondo blanco mediante los codecs existentes.
- GIF e imágenes con varios fotogramas aportan su primer fotograma por archivo.
- La salida automática usa un nombre libre junto a las imágenes. Una salida
  explícita existente se rechaza; los originales no se sobrescriben.
- Reserva exclusiva del nombre, archivo temporal en la misma carpeta y
  publicación con `os.replace`. Cancelación o error limpia la salida parcial.
- La tarjeta compartida muestra avance, ofrece cancelar al pasar el puntero y
  se cierra después de publicar el PDF. Los errores permanecen visibles.
- El PDF conserva proporciones de las imágenes, a 150 dpi. Los ajustes A4/Carta
  de documentos son un flujo distinto. SVGZ no se anuncia como soportado.

## Componentes visuales reutilizables

| Componente | Implementación y criterio |
| --- | --- |
| Contenedor del editor | `ToolDialog`, esquinas redondas y material HUD existente |
| Tipografía y colores | `theme.py`, Segoe UI, paletas clara/oscura y acento Tangerine |
| Orden de páginas | Lista numerada, ruta completa en tooltip, modos nombre/recibido/manual |
| Reordenación | Chips Subir/Bajar, activos en modo Manual |
| Distribución y etiquetas | Controles Qt integrados en el formulario compartido |
| Acción principal | Botón naranja Crear PDF; validación junto al campo de salida |
| Progreso | `ProgressWindow`, barra naranja, anclaje al cursor y autocierre |
| Ajustes de Explorer | Acceso al editor y acción Instalar/reparar con resultado visible |

Estos son los componentes y estados que debe conservar una futura iteración en
OpenDesign. Los renders de revisión provienen de los widgets reales en modo
offscreen, con fuentes instaladas cargadas explícitamente. No se ha publicado
un diseño remoto ni se presenta una maqueta como ejecución real de Explorer.

![Editor Qt en español, tema oscuro](images/image-pdf-dark.png)

![Integración en ajustes de Tangerine](images/explorer-settings-dark.png)

## Validación reproducible

```powershell
python -m pytest -q
python main.py --smoke-image-pdf
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build.ps1
```

La comprobación `--smoke-image-pdf` usa archivos temporales y una cola aislada.
Crea PDF de una y tres imágenes, ejecuta el CLI en procesos secundarios reales,
entrega sus peticiones por el canal local a `Controller.handle_request`, valida
las páginas, la limpieza del manifiesto y el autocierre. No registra extensiones.

El build también compila y ejecuta `shell_selection_contract` mediante CTest:
selección simple, múltiple y filtrado de selección mixta/no compatible. No abre
un menú ni invoca un comando. El log nativo obtiene el nombre real del proceso;
un harness no se identifica como `explorer.exe`.

Las pruebas de registro y accesos directos usan una rama temporal de HKCU y una
carpeta SendTo temporal. Cubren lectura posterior, reparación repetida,
desinstalación propia y conservación de registros ajenos.

El workflow de GitHub ejecuta regresiones, build nativo, validaciones del
ejecutable congelado, exige instalador y comprueba que el tag coincida con la
versión antes de publicar. Incluye la reparación previa de Qt WebEngine/ICU
preparada para 1.9.2 y ahora incorporada en 1.10.0.

## Evidencia local de esta integración

- Cambios previos conservados: `build/integration-evidence/20261008-184557/before.diff`.
- Regresión final: 214 aprobadas, 1 omitida. El recibo final se guarda en
  `build/integration-evidence/20261008-184557/pytest-final.txt`.
- Smoke de código fuente: `ok=true`, versión 1.10.0, 2 peticiones IPC, PDF de
  1 y 3 páginas, limpieza del manifiesto y autocierre confirmados.
- Renders de los widgets en español: carpeta local de evidencia, `pdf-True.png`,
  `pdf-False.png`, `settings-True.png`, `settings-False.png`.
- Validación del paquete, instalación y lectura del registro: completar con los
  recibos de la compilación final antes de dar la entrega por terminada.

### Diagnóstico del build local

El primer paquete ejecutó correctamente imágenes a PDF, pero WebEngine terminó
con `STATUS_DLL_NOT_FOUND` al ejecutar sus procesos aislados desde el workspace.
La prueba temporal sin sandbox pasó; no se incorpora esa desactivación al app.
El mismo paquete copiado a `%LOCALAPPDATA%/TangerineValidation/20261008/Tangerine`
pasó con el sandbox activo. El helper del entorno Python también pasó.

La evidencia demuestra dependencia de la ubicación/entorno de ejecución, no una
DLL concreta ausente. El workspace y el destino tienen ACL distintas; atribuir
el fallo a una ACE específica todavía sería una inferencia. La compilación final
se valida en `%LOCALAPPDATA%/TangerineBuilds/1.10.0`, antes de instalar por usuario.
El ZIP/instalador transporta los archivos del paquete y usa permisos del destino.

## Fuentes revisadas el 2026-10-08

- [Gist original de nobucshirai](https://gist.github.com/nobucshirai/d5216fe9fa1b1fb719c05c880866cd66):
  comportamiento solicitado de combinación, cuadrícula y etiquetas. El motor
  nuevo implementa ese flujo usando las dependencias existentes de Tangerine.
- [Microsoft: Creating Shortcut Menu Handlers](https://learn.microsoft.com/en-us/windows/win32/shell/context-menu-handlers):
  interfaces de menú, activación y registro por usuario.
- [Microsoft: Verb Selection Model](https://learn.microsoft.com/en-us/windows/win32/shell/how-to-employ-the-verb-selection-model):
  selección múltiple y modelos de invocación.
- [Qt: QLocalServer](https://doc.qt.io/qtforpython-6/PySide6/QtNetwork/QLocalServer.html):
  canal local y opción de acceso por usuario.

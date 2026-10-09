# Estado de botones después de sincronizar el lienzo — 1.10.2

La revisión visual final de 1.10.1 mostró que el valor de anchura cambiaba
después de un arrastre, pero el botón de aumento seguía con su estado anterior.
Dos pruebas reprodujeron el fallo en `NumericSpinBox` y `NumericDoubleSpinBox`:
máximo → bloquear señales → valor intermedio → flecha aún deshabilitada.

`CropImageDialog._rect_changed()` bloquea señales para no volver a ejecutar
el cambio de dimensiones. Los controles dependían exclusivamente de
`valueChanged` para refrescar sus botones. Ahora también sincronizan el estado
al cambiar el valor desde código, conservando el bloqueo de señales de Qt.

Las pruebas nuevas cubren la transición en enteros y decimales. El smoke del
ejecutable reproduce además arrastrar un recorte, sincronizar sus campos y
pulsar el botón de aumento. Esta comprobación se incorpora al empaquetado y
a la validación de la instalación.

1.10.1 permanece publicada con su etiqueta original; esta corrección se
distribuye como 1.10.2. Las demás reparaciones se describen en la
[auditoría anterior](editor-repair-1.10.1.md).

Verificación fuente del 2026-10-09: **269 passed, 1 skipped**, 38.21 s.
`python main.py --smoke-editors` terminó con código 0 e incluye la comprobación
`blocked_signal_refresh: true` y el clic después de arrastrar el recorte.

![Botones activos después de sincronizar el recorte](images/crop-1.10.2-dark.png)

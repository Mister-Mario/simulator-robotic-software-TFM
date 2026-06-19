"""Traducción de instrucciones legibles del actuador lineal a su forma
compacta numérica, para publicarlas por MQTT al Arduino del gemelo digital.

Formato legible (lo que el usuario escribe en la consola):
    C O | C F                 -> control on / off
    M <M|S> <C|D> <valor>     -> movimiento medido
                                 (Motor/Sensor, Cambios/Distancia en mm)
    L <M|S>                   -> mover hasta el límite Motor / Sensor
    J <M|S>                   -> jog: mover continuo hacia Motor / Sensor (control en vivo)
    J P  (o STOP)             -> parar el jog

Formato compacto (lo que se publica por MQTT, barato de parsear en el micro):
    Control:     0,<0|1>
    Movimiento:  1,<dir>,<modo>,<valor>   dir 0=motor 1=sensor · modo 0=cambios 1=distancia
    Límite:      2,<dir>                   dir 0=motor 1=sensor
    Jog (vivo):  3,<dir>                   dir 0=motor 1=sensor (mover continuo hasta parar/tope)
    Parar:       4

La conversión distancia(mm) -> cambios la sigue haciendo el Arduino (conserva su
factor de calibración); aquí solo se marca el modo y se pasa el valor tal cual.

Calibración píxeles(simulador) <-> cambios(físico). El bloque del actuador en el
simulador recorre de x=508 a x=1912 (una pasada completa), y una pasada del actuador
físico son 140 cambios (= 240 mm a 1.71 mm/cambio). Único punto de verdad para que el
recorrido del simulador equivalga al del robot real.
"""

PIXELES_POR_PASADA = 1912 - 508   # recorrido del bloque del simulador (px)
CAMBIOS_POR_PASADA = 140          # cambios del opto interruptor en una pasada física
MM_POR_CAMBIO = 1.71              # calibración del actuador físico
PX_POR_CAMBIO = PIXELES_POR_PASADA / CAMBIOS_POR_PASADA            # ~10.03 px por cambio
PX_POR_MM = PIXELES_POR_PASADA / (CAMBIOS_POR_PASADA * MM_POR_CAMBIO)  # ~5.86 px/mm


class TranslationError(ValueError):
    """Instrucción legible inválida. El mensaje es apto para mostrar en consola."""
    pass


_DIR = {"M": 0, "S": 1}   # lado del actuador: Motor / Sensor
_MODO = {"C": 0, "D": 1}  # interpretación del valor: Cambios / Distancia (mm)


def encode(text):
    """Traduce una instrucción legible a su forma compacta numérica.

    Devuelve la cadena compacta lista para publicar. Lanza ``TranslationError``
    con un mensaje explicativo si la instrucción no es válida.
    """
    tokens = (text or "").strip().split()
    if not tokens:
        raise TranslationError("instrucción vacía")

    head = tokens[0].upper()

    # --- CONTROL: C O / C F ---
    if head == "C":
        if len(tokens) != 2 or tokens[1].upper() not in ("O", "F"):
            raise TranslationError("uso: 'C O' o 'C F'")
        return "0,1" if tokens[1].upper() == "O" else "0,0"

    # --- LÍMITE: L M / L S ---
    if head == "L":
        if len(tokens) != 2 or tokens[1].upper() not in _DIR:
            raise TranslationError("uso: 'L M' o 'L S'")
        return "2,{}".format(_DIR[tokens[1].upper()])

    # --- PARAR JOG: STOP ---
    if head == "STOP":
        if len(tokens) != 1:
            raise TranslationError("uso: 'STOP'")
        return "4"

    # --- JOG: J M / J S / J P ---
    if head == "J":
        if len(tokens) != 2:
            raise TranslationError("uso: 'J M' | 'J S' | 'J P'")
        arg = tokens[1].upper()
        if arg == "P":
            return "4"
        if arg not in _DIR:
            raise TranslationError("uso: 'J M' | 'J S' | 'J P'")
        return "3,{}".format(_DIR[arg])

    # --- MOVIMIENTO: M <M|S> <C|D> <valor> ---
    if head == "M":
        if len(tokens) != 4:
            raise TranslationError("uso: 'M <M|S> <C|D> <valor>'")
        direccion = tokens[1].upper()
        modo = tokens[2].upper()
        if direccion not in _DIR:
            raise TranslationError("dirección debe ser M (motor) o S (sensor)")
        if modo not in _MODO:
            raise TranslationError("modo debe ser C (cambios) o D (distancia)")
        valor = _parse_valor(tokens[3], modo)
        return "1,{},{},{}".format(_DIR[direccion], _MODO[modo], valor)

    raise TranslationError("comando desconocido: " + tokens[0])


import collections

# Reporte de vuelta del actuador físico al simulador.
#   pos        = posición absoluta en cambios desde el extremo motor (0..140).
#   lim_motor  = final de carrera del motor pulsado (True/False), o None si no se reporta.
#   lim_sensor = final de carrera del sensor pulsado (True/False), o None si no se reporta.
TwinFeedback = collections.namedtuple(
    "TwinFeedback", ["pos", "lim_motor", "lim_sensor"])


def parse_position(text):
    """Decodifica un reporte del actuador físico (robot -> simulador).

    Formatos aceptados:
        ``5,<pos>``                        solo posición (lim_* = None)
        ``5,<pos>,<limMotor>,<limSensor>`` posición + estado de los finales (1=pulsado)

    Devuelve un ``TwinFeedback`` o ``None`` si el texto no es un reporte válido.
    """
    parts = [p.strip() for p in (text or "").strip().split(",")]
    if len(parts) not in (2, 4) or parts[0] != "5":
        return None
    try:
        pos = int(parts[1])
    except ValueError:
        return None
    lim_motor = lim_sensor = None
    if len(parts) == 4:
        try:
            lim_motor = int(parts[2]) != 0
            lim_sensor = int(parts[3]) != 0
        except ValueError:
            return None
    return TwinFeedback(pos, lim_motor, lim_sensor)


def _parse_valor(raw, modo):
    """Valida y normaliza el valor numérico (float si es distancia, int si cambios)."""
    try:
        valor = float(raw) if modo == "D" else int(raw)
    except ValueError:
        raise TranslationError("valor numérico inválido: " + raw)
    if valor <= 0:
        raise TranslationError("el valor debe ser mayor que 0")
    # Evita decimales innecesarios en la trama compacta (5.0 -> "5").
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)

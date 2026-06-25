"""Tests de decodificación del coche (digital_twin/translators.py): reporte de
pose de los encoders y trama de sensores (infrarrojos + distancia).

Ejecutar desde la raíz del repositorio:
    python -m unittest Simulador/simulator/digital_twin/tests/test_coche_decodificacion.py
"""

import os
import sys
import unittest

# El módulo a probar vive en el simulador; lo hacemos importable subiendo tres
# niveles: tests -> digital_twin -> simulator.
_DIRECTORIO_SIMULADOR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _DIRECTORIO_SIMULADOR not in sys.path:
    sys.path.insert(0, _DIRECTORIO_SIMULADOR)

import digital_twin.translators as translators  # noqa: E402


class TestCocheDecodificacion(unittest.TestCase):
    """Decodificación del reporte de pose del coche -> simulador.

    Formato: '5,<cambiosDerecha>,<cambiosIzquierda>[,<tipoMovimiento>]'.
    """

    def setUp(self):
        self.traductor = translators.CarTranslator()

    def test_reporte_valido(self):
        reporte = self.traductor.decode("5,40,38")
        self.assertEqual((reporte.cambios_der, reporte.cambios_izq), (40, 38))
        # 3 campos (modo control): el sentido lo pone el simulador, no la trama.
        self.assertIsNone(reporte.motion)
        self.assertEqual(self.traductor.decode("  5 , 0 , 0 ").cambios_der, 0)  # tolera espacios

    def test_reporte_autonomo_con_tipo_de_movimiento(self):
        # 4º campo = tipo de movimiento (0=avanzar, 1=retroceder, 2=izquierda,
        # 3=derecha), usado en modo autónomo.
        self.assertEqual(self.traductor.decode("5,10,10,0").motion, "A")
        self.assertEqual(self.traductor.decode("5,10,10,1").motion, "R")
        self.assertEqual(self.traductor.decode("5,32,32,2").motion, "I")
        reporte = self.traductor.decode("5,32,32,3")
        self.assertEqual(
            (reporte.cambios_der, reporte.cambios_izq, reporte.motion),
            (32, 32, "D"))

    def test_no_es_reporte(self):
        # Comandos del simulador al robot, código de movimiento inválido (4º campo)
        # u otros textos no valen.
        for texto in ("3,0", "4", "hola", "5,abc,1", "5,1", "5,1,2,9", "5,1,2,x", ""):
            self.assertIsNone(self.traductor.decode(texto), texto)


class CapaSensoresFalsa:
    """Captura lo que apply_to_sim reflejaría en los sensores (sin canvas real)."""

    def __init__(self):
        self.infrarrojos = None
        self.distancia = "sin asignar"

    def apply_twin_sensors(self, valores_infrarrojos, distancia_cm):
        self.infrarrojos = valores_infrarrojos
        self.distancia = distancia_cm


class TestCocheSensores(unittest.TestCase):
    """Trama de sensores del coche -> simulador.

    Formato: '7,<infrarrojos...>,<distanciaCm>'.
    """

    def setUp(self):
        self.traductor = translators.CarTranslator()

    def test_decodifica_sensores_validos(self):
        # 4 infrarrojos (izquierda -> derecha) + distancia en centímetros.
        reporte = self.traductor.decode("7,1,0,1,0,23.5")
        self.assertEqual(reporte.ir, (1, 0, 1, 0))
        self.assertAlmostEqual(reporte.dist_cm, 23.5)
        self.assertEqual(self.traductor.decode(" 7 , 1 , 1 , 0 , 0 , 5 ").ir, (1, 1, 0, 0))

    def test_decodifica_sin_eco_devuelve_none(self):
        # Distancia negativa (sin eco / fuera de alcance) -> distancia = None.
        reporte = self.traductor.decode("7,0,0,0,0,-1")
        self.assertEqual(reporte.ir, (0, 0, 0, 0))
        self.assertIsNone(reporte.dist_cm)

    def test_decodifica_normaliza_bits(self):
        # Cualquier valor distinto de cero se normaliza a 1.
        self.assertEqual(self.traductor.decode("7,5,0,2,0,10").ir, (1, 0, 1, 0))

    def test_decodifica_numero_variable_de_infrarrojos(self):
        # 2 o 3 infrarrojos también valen (mobile2 / mobile3).
        self.assertEqual(self.traductor.decode("7,1,0,3.0").ir, (1, 0))
        self.assertEqual(self.traductor.decode("7,1,1,0,5").ir, (1, 1, 0))

    def test_decodifica_sensores_invalido(self):
        # Falta la distancia, infrarrojo no numérico o distancia no numérica -> no es reporte.
        for texto in ("7", "7,1", "7,a,0,1.0", "7,1,0,x"):
            self.assertIsNone(self.traductor.decode(texto), texto)

    def test_reflejo_llama_a_apply_twin_sensors(self):
        capa = CapaSensoresFalsa()
        self.traductor.apply_to_sim(capa, self.traductor.decode("7,1,0,1,0,23.5"))
        self.assertEqual(capa.infrarrojos, (1, 0, 1, 0))
        self.assertAlmostEqual(capa.distancia, 23.5)
        # Sin eco: el None de la distancia llega tal cual a la capa.
        self.traductor.apply_to_sim(capa, self.traductor.decode("7,0,0,0,0,-1"))
        self.assertEqual(capa.infrarrojos, (0, 0, 0, 0))
        self.assertIsNone(capa.distancia)


if __name__ == "__main__":
    unittest.main(verbosity=2)

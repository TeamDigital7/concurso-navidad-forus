"""Reglas de "Forus y el Cáliz de los Campeones" (PPT Concurso Navidad Forus 2026).

Todo lo que viene del reglamento vive aquí: casas, tiendas, calendario de puntos,
bonus, competencias, premios y maestros. El cálculo está en `puntos.py`.
"""
from dataclasses import dataclass
from datetime import date

INICIO = date(2026, 11, 1)
FIN = date(2026, 12, 31)

# ---------- Casas ----------
CASAS = {
    "Speed": {
        "animal": "Tigre", "escudo": "speed.webp",
        "color": "#1E6FD9", "acento": "#E8B923", "fondo": "#0E2A55",
    },
    "Curiosity": {
        "animal": "Mangosta", "escudo": "curiosity.webp",
        "color": "#1F2E52", "acento": "#B9C0CC", "fondo": "#121B33",
    },
    "Ownership": {
        "animal": "Águila", "escudo": "ownership.webp",
        "color": "#D4A51C", "acento": "#F3D778", "fondo": "#3A2C06",
    },
    "Accountability": {
        "animal": "Lobo", "escudo": "accountability.webp",
        "color": "#1F6B2E", "acento": "#8FC79A", "fondo": "#0E2A15",
    },
    "Agility": {
        "animal": "Lémur", "escudo": "agility.webp",
        "color": "#7A1418", "acento": "#C9A3A3", "fondo": "#2E0B0D",
    },
}

# Tiendas ("magos") por casa, tal como figuran en el PPT.
# "*" en el PPT queda en NOTAS_TIENDA (pendiente confirmar qué significa).
TIENDAS = {
    "Speed": [
        "AZALEIA PUCALLPA", "AZALEIA HUÁNUCO", "AZALEIA CUSCO", "AZALEIA PIURA",
        "AZALEIA PORONGOCHE", "AZALEIA CHICLAYO", "AZALEIA PORTAL PIZARRO",
        "AZALEIA LAMBRAMANI", "AZALEIA PRIMAVERA", "AZALEIA MEGA PLAZA",
        "AZALEIA PLAZA NORTE", "AZALEIA MALL DEL SUR", "AZALEIA SAN MIGUEL",
        "AZALEIA JOCKEY PLAZA", "AZALEIA ASIA", "OLYMPIKUS MEGA PLAZA",
        "SE HUALLAGA", "SE SURCO",
    ],
    "Accountability": [
        "RKF AREQUIPA", "RKF CUSCO 2", "RKF CUSCO", "RKF TRUJILLO", "RKF CAYMA",
        "RKF ICA", "RKF JOCKEY", "RKF LARCOMAR 2", "RKF SALAVERRY", "RKF LA MOLINA",
        "RKF ASIA 2", "PARFOIS JOCKEY PLAZA", "PARFOIS SAN MIGUEL", "PARFOIS LARCOMAR",
        "PARFOIS TRUJILLO", "PAT CUSCO", "PAT LARCOMAR",
    ],
    "Curiosity": [
        "HP CAYMA", "HP CHICLAYO", "HP CUSCO", "HP PIURA 2", "HP TRUJILLO", "HP JOCKEY",
        "HP SAN MIGUEL 2", "HP PLAZA NORTE", "HP SALAVERRY 2", "HP CHACARILLA",
        "HP LARCOMAR", "HP PLAZA ANGAMOS", "HP CHORRILLOS", "HP LA MOLINA",
        "HPK JOCKEY", "HPK PLAZA NORTE",
    ],
    "Agility": [
        "VANS TRUJILLO", "VANS PIURA", "VANS CHICLAYO", "VANS PARQUE LA MOLINA",
        "VANS JOCKEY PLAZA", "VANS SAN MIGUEL", "VANS SALAVERRY", "VANS PLAZA NORTE",
        "VANS OUTLET JOCKEY", "DH LURIN", "DH AEROPUERTO 2", "FB OVALO PAPAL TRUJILLO",
        "FB MINKA", "FB CAMACHO", "BSOUL JOCKEY PLAZA", "BSOUL LA MOLINA", "BSOUL ASIA",
    ],
    "Ownership": [
        "CLB JOCKEY PLAZA", "CLB SAN MIGUEL", "CLB SALAVERRY", "CLB LARCOMAR",
        "CLB PLAZA NORTE", "CLB LA MOLINA", "CLB MALL DEL SUR", "CLB PARQUE LA MOLINA",
        "CLB ANGAMOS", "CLB TRUJILLO", "CLB CAYMA", "CLB CAJAMARCA", "CLB CUSCO",
        "CLB PIURA", "CLB CUSCO PLAZA", "CLB ICA", "CLB CHICLAYO",
        "CLB HUANCAYO", "CLB PORONGOCHE", "CLB MINKA", "CLB ASIA", "CLB OUTLET JOCKEY",
    ],
}
NOTAS_TIENDA = {
    "PARFOIS LARCOMAR": "*", "PARFOIS TRUJILLO": "*", "VANS OUTLET JOCKEY": "*",
}
TIENDA_A_CASA = {t: casa for casa, ts in TIENDAS.items() for t in ts}


# ---------- Calendario de puntos (cumplimiento de venta vs. presupuesto) ----------
@dataclass(frozen=True)
class Tramo:
    inicio: date
    fin: date
    puntos: int


TRAMOS = [
    Tramo(date(2026, 11, 1), date(2026, 11, 5), 10),
    Tramo(date(2026, 11, 6), date(2026, 11, 8), 12),
    Tramo(date(2026, 11, 9), date(2026, 11, 12), 15),
    Tramo(date(2026, 11, 13), date(2026, 11, 15), 20),
    Tramo(date(2026, 11, 16), date(2026, 11, 19), 10),
    Tramo(date(2026, 11, 20), date(2026, 11, 22), 12),
    Tramo(date(2026, 11, 23), date(2026, 11, 26), 15),
    Tramo(date(2026, 11, 27), date(2026, 11, 30), 20),
    Tramo(date(2026, 12, 1), date(2026, 12, 3), 10),
    Tramo(date(2026, 12, 4), date(2026, 12, 6), 12),
    Tramo(date(2026, 12, 7), date(2026, 12, 10), 15),
    Tramo(date(2026, 12, 11), date(2026, 12, 15), 25),
    Tramo(date(2026, 12, 16), date(2026, 12, 20), 18),
    Tramo(date(2026, 12, 21), date(2026, 12, 24), 20),
    # El 25 de diciembre no figura en el PPT
    Tramo(date(2026, 12, 26), date(2026, 12, 27), 25),
    Tramo(date(2026, 12, 28), date(2026, 12, 31), 30),
]

# Puntos bonus por tramo
BONUS_FIDELIZACION = {"umbral": 0.70, "puntos": 5}   # fidelización mayor al 70%
BONUS_SSS = {"umbral": 0.10, "puntos": 5}            # crecimiento SSS mayor al 10%


# ---------- Competencias y premios ----------
@dataclass(frozen=True)
class Competencia:
    nombre: str
    inicio: date
    fin: date
    pago: date
    premios: tuple  # S/ por puesto 1..5 (neto)


COMPETENCIAS = [
    Competencia("La Copa de Quidditch", date(2026, 11, 1), date(2026, 11, 15), date(2026, 11, 20),
                (800, 700, 600, 500, 400)),
    Competencia("La Cámara de los Desafíos", date(2026, 11, 16), date(2026, 11, 30), date(2026, 12, 4),
                (800, 700, 600, 500, 400)),
    Competencia("La Batalla de las Casas", date(2026, 12, 1), date(2026, 12, 15), date(2026, 12, 22),
                (1000, 800, 600, 500, 400)),
    Competencia("El Torneo de los Magos", date(2026, 12, 16), date(2026, 12, 31), date(2027, 1, 8),
                (1500, 1300, 1100, 900, 700)),
]
GANADORES_POR_CASA = 5
FACTOR_PART_TIME = 0.5
PREMIO_CAMPEON = "1 paquete doble todo incluido a Cartagena, Colombia (4 días - 3 noches)"

# % del premio que se paga según cumplimiento de todo el canal Retail (al cierre de cada etapa)
RANGO_PAGO = [  # (desde, factor) — se toma el último cuyo "desde" se alcanza
    (0.95, 0.50),
    (0.975, 0.75),
    (1.00, 1.00),
    (1.05, 1.10),
]

DESAFIOS_SSS = {11: 0.24, 12: 0.23}  # meta de crecimiento SSS del canal por mes

GANADOR_2025 = "CLB CHICLAYO"

# ---------- Maestros (responsables por centro comercial / tienda) ----------
MAESTROS_CC = [
    ("MEGA PLAZA y PLAZA NORTE", "HP · HPK · CLB / VANS · AZA / OLY",
     ["Ana Santa Maria", "Candi Rios", "Karina Ramirez", "Cesar Fernandez", "Hilda Mozo"]),
    ("JOCKEY PLAZA / CAMACHO", "HP / HPK · VANS / CLB · RKF · BSOUL · PARFOIS · FB CAMACHO",
     ["Clara Gallastegui", "Lucia Cornejo", "Alejandro Espinoza", "Nelly Baca", "Amanda Arroyo"]),
    ("LARCOMAR", "HP · CLB / PAT · RKF", ["Melisa Senador", "Sebastian Mansilla", "Daniela Ballon"]),
    ("SAN MIGUEL", "HP · CLB / VANS · AZA / PARFOIS",
     ["Ediht Ruiz", "Diego Navarro", "Luis Nuñez", "Gabriela Montero", "Josue Navarro"]),
    ("ANGAMOS / CHACARILLA / PRIMAVERA", "HP · CLB · AZA", ["Edu Gerbi", "Romulo Rasilla"]),
    ("SALAVERRY", "HP · VANS · CLB · RKF",
     ["Mario Biggio", "Stephanie G.", "Ariana Gamarra", "Valeria Jimenez"]),
    ("AEROPUERTO", "DH", ["Percy Rojas", "Milagros Ono"]),
    ("HUALLAGA", "HP", ["Milagros Martinez"]),
    ("SURCO / CHORRILLOS", "SE · HP", ["Sara Meneses", "Hugo Camara", "Andrea Ventocilla"]),
    ("LURIN / MALL SUR", "DH · CLB · AZA", ["Rosa Terrones", "Janet Perez"]),
    ("CENCO LA MOLINA / PARQUE LA MOLINA", "HP / RKF · CLB / BSOUL · VANS",
     ["Alejandro Mosqueira", "Nicolas Rodriguez"]),
]
MAESTROS_TIENDA = {
    "CLB PIURA": "Alejandro Mosqueira", "CLB CUSCO PLAZA": "Diego Navarro",
    "VANS TRUJILLO": "Lucia Cornejo", "HP CAYMA": "Mario Biggio", "RKF AREQUIPA": "Gaby Montero",
    "RKF CUSCO 2": "Hugo Camara", "PTG CUSCO": "Daniela Ballon", "RKF TRUJILLO": "Clara Gallastegui",
    "CLB CUSCO": "Melisa Senador", "CLB CAYMA": "Alejandro Mosqueira",
    "VANS PIURA": "Alejandro Espinoza", "FB TRUJILLO": "Percy Rojas", "HP PIURA": "Mario Biggio",
    "CLB CHICLAYO": "Anthony Fernandez", "CLB ICA": "Janet Perez", "RKF CUSCO": "Stephanie Grozo",
    "CLB CAJAMARCA": "Daniela Ballon", "HP CHICLAYO": "Ana Santamaria", "HP CUSCO": "Ariana Gamarra",
    "HP TRUJILLO": "Rosa Terrones", "RKF CAYMA": "Milagros Martinez", "RKF ICA": "Karina Ramirez",
    "CLB HUANCAYO": "Fernando Quichiz", "CLB TRUJILLO": "Daniela Ballon",
    "PARFOIS TRUJILLO": "Ariana Gamarra", "VANS CHICLAYO": "Alejandro Espinoza",
    "AZA CUSCO": "Hilda Mozo", "AZA TRUJILLO": "Hilda Mozo", "AZA PIURA": "Andrea Ventocilla",
    "AZA PUCALLPA": "Rosa Terrones", "AZA HUANUCO": "Candi Rios", "AZA PORONGOCHE": "Patrick Leyva",
    "AZA LAMBRAMANI": "Patrick Leyva", "AZA CHICLAYO": "Amanda Arroyo",
}

REGLAMENTO = [
    "Durante noviembre y diciembre las tiendas se convierten en Casas de Magia que compiten por "
    "demostrar quiénes son los mejores magos.",
    "El torneo se divide en competencias de máximo 16 días; en cada una los magos superan desafíos "
    "ligados a sus objetivos comerciales y suman puntos.",
    "Al cierre de cada competencia, los 5 magos con más puntos de cada casa son los ganadores.",
    "Desempate: mejor % de cumplimiento de venta vs. presupuesto.",
    "La Copa del Mejor Mago del Retail es para el mago con más puntos sumando todas las competencias "
    "de noviembre y diciembre.",
    "Los premios aplican solo si el cumplimiento de presupuesto de todo el canal Retail es ≥ 95%.",
    "Los part times reciben el 50% del premio. Pago de premios neto.",
]

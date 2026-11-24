import html
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime
from functools import lru_cache

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "images")
LABO_FILES_DIR = os.path.join(IMG_DIR, "labo_attachments")

SGH_DICT = {
    "SGH01": ("Explosif", "sgh01.png"),
    "SGH02": ("Inflammable", "sgh02.png"),
    "SGH04": ("Gaz sous pression", "sgh04.png"),
    "SGH05": ("Corrosif", "sgh05.png"),
    "SGH06": ("Toxique aigu", "sgh06.png"),
    "SGH07": ("Nocif / Irritant", "sgh07.png"),
    "SGH08": ("Danger santé / CMR", "sgh08.png"),
    "SGH09": ("Dangereux env.", "sgh09.png"),
}


def _sgh_diamond(inner_svg: str) -> str:
    return (
        '<svg class="sgh-svg" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        '<polygon points="32,3 61,32 32,61 3,32" fill="#ffffff" stroke="#dc2626" stroke-width="4.4" stroke-linejoin="round"/>'
        f"{inner_svg}"
        "</svg>"
    )


SGH_SVG_MAP = {
    "SGH01": _sgh_diamond(
        '<circle cx="24" cy="36" r="6.2" fill="#111827"/>'
        '<path d="M29 31 L34 26 M32 22 L35 16 M38 25 L45 21 M39 32 L47 32 M37 38 L44 43 M31 41 L34 48" stroke="#111827" stroke-width="2.4" stroke-linecap="round"/>'
        '<polygon points="34,26 39,23 37,29 42,32 36,34 38,39 33,35 29,31" fill="#111827"/>'
    ),
    "SGH02": _sgh_diamond(
        '<path d="M32 15 C36 22 42 26 42 34 C42 40 37.5 44 32 44 C26.5 44 22 40 22 34 C22 29 25 25 27 22 C26.5 26 28.5 28 30 27 C29 22 30.5 18 32 15 Z" fill="#111827"/>'
        '<path d="M32 31 C34 34 35.5 36 35.5 38.5 C35.5 41 34 42.5 32 42.5 C30 42.5 28.5 41 28.5 38.5 C28.5 36.5 30 34 32 31 Z" fill="#ffffff"/>'
        '<line x1="21" y1="47" x2="43" y2="47" stroke="#111827" stroke-width="2.6" stroke-linecap="round"/>'
    ),
    "SGH04": _sgh_diamond(
        '<g transform="rotate(-45 32 32)">'
        '<rect x="16" y="26.5" width="26" height="11" rx="5.5" fill="#111827"/>'
        '<rect x="41" y="29.5" width="5" height="5" rx="1" fill="#111827"/>'
        '<line x1="46" y1="27.5" x2="46" y2="36.5" stroke="#111827" stroke-width="2.4" stroke-linecap="round"/>'
        '</g>'
    ),
    "SGH05": _sgh_diamond(
        '<path d="M18 22 L28 28 L26 31 L16 25 Z" fill="#111827"/>'
        '<path d="M46 22 L36 28 L38 31 L48 25 Z" fill="#111827"/>'
        '<circle cx="26" cy="34.5" r="1.7" fill="#111827"/>'
        '<circle cx="38" cy="34.5" r="1.7" fill="#111827"/>'
        '<path d="M16 41 L29 41 L29 45 L16 45 Z" fill="#111827"/>'
        '<path d="M35 41 C37 39 42 39 47 41 C48 42.5 47 45 45 45 L35 45 Z" fill="#111827"/>'
    ),
    "SGH06": _sgh_diamond(
        '<path d="M23 28 C23 21.5 27 18 32 18 C37 18 41 21.5 41 28 C41 31.5 39 34 37.2 35 L37.2 38 L26.8 38 L26.8 35 C25 34 23 31.5 23 28 Z" fill="#111827"/>'
        '<circle cx="28.3" cy="28" r="2.3" fill="#ffffff"/>'
        '<circle cx="35.7" cy="28" r="2.3" fill="#ffffff"/>'
        '<polygon points="32,31 30.5,34 33.5,34" fill="#ffffff"/>'
        '<line x1="20" y1="45" x2="44" y2="38" stroke="#111827" stroke-width="2.8" stroke-linecap="round"/>'
        '<line x1="20" y1="38" x2="44" y2="45" stroke="#111827" stroke-width="2.8" stroke-linecap="round"/>'
    ),
    "SGH07": _sgh_diamond(
        '<path d="M29.2 19 C29.2 17.5 30.4 16.5 32 16.5 C33.6 16.5 34.8 17.5 34.8 19 L33.8 36.5 C33.7 37.6 32.9 38.3 32 38.3 C31.1 38.3 30.3 37.6 30.2 36.5 Z" fill="#111827"/>'
        '<circle cx="32" cy="44.5" r="3.2" fill="#111827"/>'
    ),
    "SGH08": _sgh_diamond(
        '<circle cx="32" cy="21" r="4.3" fill="#111827"/>'
        '<path d="M21 44 C21.5 33 25 27.5 32 27.5 C39 27.5 42.5 33 43 44 Z" fill="#111827"/>'
        '<polygon points="32,29 33.6,33.5 38.2,32.5 35,36 37.8,39.8 33.3,38.4 32,43 30.7,38.4 26.2,39.8 29,36 25.8,32.5 30.4,33.5" fill="#ffffff"/>'
    ),
    "SGH09": _sgh_diamond(
        '<path d="M26 42 L26 24 M26 30 L20 25 M26 27 L31 21 M26 33 L32 29" stroke="#111827" stroke-width="2.4" stroke-linecap="round"/>'
        '<path d="M16 42 Q24 39 32 42 T48 42" fill="none" stroke="#111827" stroke-width="2.2"/>'
        '<path d="M33 46 C36 42.5 42 42.5 45 45.5 C42 48.5 36 48.5 33 46 Z" fill="#111827"/>'
        '<polygon points="33,46 29.5,43.8 29.5,48.2" fill="#111827"/>'
    ),
}

BASE_COLS = [
    "Produit final", "Réaction 1", "Réaction 2", "Réactifs 1", "Réactifs 2",
    "Réactifs 3", "Réactifs 4", "Rendement", "Conditions opératoires", "Commentaire",
    "Numéro CAS", "Formule brute & masse", "État physique", "Pictogrammes danger",
    "Rareté & Coût", "Conditions de stockage",
]

FAST_SMILES_MAP = {
    "linalol": "CC(C)=CCCC(C)(O)C=C", "acide phosphorique": "OP(=O)(O)O",
    "acide anthranilique": "Nc1ccccc1C(=O)O", "méthanol": "CO",
    "acide p-toluènesulfonique": "Cc1ccc(S(=O)(=O)O)cc1", "acide butanoïque": "CCCC(=O)O",
    "éthanol": "CCO", "alcool benzylique": "OCc1ccccc1", "anhydride acétique": "CC(=O)OC(=O)C",
    "acétate de sodium": "CC(=O)[O-].[Na+]", "heptan-1-ol": "CCCCCCCO",
    "acrylate de méthyle": "COC(=O)C=C", "peroxyde de di-tert-butyle": "CC(C)(C)OOC(C)(C)C",
    "benzène": "c1ccccc1", "oxyde d'éthylène": "C1CO1", "trichlorure d'aluminium": "Cl[Al](Cl)Cl",
    "myrcène": "CC(=CCCC(=C)C=C)C", "acide chlorhydrique": "Cl",
    "hydroxyde de sodium (naoh)": "[OH-].[Na+]", "citral": "CC(C)=CCCC(C)=CC=O",
    "acétone": "CC(=O)C", "trifluorure de bore éthérate": "FB(F)F",
    "p-tert-butylbenzaldéhyde": "CC(C)(C)c1ccc(C=O)cc1", "propanal": "CCC=O",
    "isosafrole": "CC=Cc1ccc2OCOc2c1", "ozone": "O=[O+][O-]", "diméthylsulfure": "CSC",
    "sclaréol": "CC1(O)CCCC2(C)C1CCC(C)(C=C)O2", "trichlorure de ruthénium": "Cl[Ru](Cl)Cl",
    "periodate de sodium": "[Na+].[O-]I(=O)(=O)=O", "3-méthyl-3-pentèn-2-one": "CC=C(C)C(=O)C",
    "5-tert-butyl-m-xylène": "CC1=CC(=CC(=C1)C(C)(C)C)C", "chlorure d'acétyle": "CC(=O)Cl",
    "mélange nitrant (hno3 / h2so4)": "[O-][N+](=O)O.OS(=O)(=O)O", "isochromane": "c1ccc2CCOCc2c1",
    "isobutylène": "CC(=C)C", "gaïacol": "COc1ccccc1O", "chlorure d'allyle": "C=CCCl",
    "carbonate de potassium": "[K+].[K+].[O-]C([O-])=O", "dérivé de l'acide kojique": "O=c1cc(CO)occ1O",
    "acétaldéhyde": "CC=O", "borohydrure de sodium": "[BH4-].[Na+]", "benzaldéhyde": "O=Cc1ccccc1",
    "butan-2-one": "CCC(=O)C", "dioxyde de sélénium": "O=[Se]=O", "acide salicylique": "Oc1ccccc1C(=O)O",
    "acide 1-pyrroline-5-carboxylique": "C1CC(=NCC1)C(=O)O", "méthylglyoxal": "CC(=O)C=O",
    "5989-27-5": "CC1=CCC(CC1)C(=C)C", "134-20-3": "COC(=O)c1ccccc1N", "105-54-4": "CCCC(=O)OCC",
    "140-11-4": "CC(=O)OCc1ccccc1", "706-14-9": "CCCCCCC1CCC(=O)O1", "60-12-8": "OCCc1ccccc1",
    "106-24-1": "CC(C)=CCCC(C)=CCO", "127-41-3": "CC1=CCCC(C)(C)C1C=CC(=O)C",
    "80-54-6": "CC(Cc1ccc(C(C)(C)C)cc1)C=O", "120-57-0": "O=Cc1ccc2OCOc2c1",
    "6790-58-5": "CC12CCCC(C)(C)C1CCC3(C)C2CCO3", "54464-57-2": "CC(=O)C1(C)CCC2C(C1)C(C)=CCC2(C)C",
    "81-15-2": "CC(=O)c1c(C)c([N+](=O)[O-])c(C(C)(C)C)c([N+](=O)[O-])c1C",
    "1222-05-5": "CC1COC2=CC3=C(C=C2C1)C(C)(C)CC3(C)C", "97-53-0": "COc1cc(CC=C)ccc1O",
    "4940-11-8": "CCc1oc(cc(=O)c1O)C", "104-55-2": "O=CC=Cc1ccccc1", "431-03-8": "CC(=O)C(=O)C",
    "119-36-8": "COC(=O)c1ccccc1O", "85228-95-9": "CC(=O)C1=NCCC1",
}

FAST_MW_MAP = {
    "linalol": 154.25, "acide phosphorique": 98.00, "acide anthranilique": 137.14,
    "méthanol": 32.04, "acide p-toluènesulfonique": 172.20, "acide butanoïque": 88.11,
    "éthanol": 46.07, "alcool benzylique": 108.14, "anhydride acétique": 102.09,
    "acétate de sodium": 82.03, "heptan-1-ol": 116.20, "acrylate de méthyle": 86.09,
    "peroxyde de di-tert-butyle": 146.23, "benzène": 78.11, "oxyde d'éthylène": 44.05,
    "trichlorure d'aluminium": 133.34, "myrcène": 136.23, "acide chlorhydrique": 36.46,
    "hydroxyde de sodium (naoh)": 40.00, "citral": 152.23, "acétone": 58.08,
    "trifluorure de bore éthérate": 141.93, "p-tert-butylbenzaldéhyde": 162.23,
    "propanal": 58.08, "isosafrole": 162.19, "ozone": 48.00, "diméthylsulfure": 62.13,
    "sclaréol": 308.50, "trichlorure de ruthénium": 207.43, "periodate de sodium": 213.89,
    "3-méthyl-3-pentèn-2-one": 98.14, "5-tert-butyl-m-xylène": 162.27, "chlorure d'acétyle": 78.50,
    "mélange nitrant (hno3 / h2so4)": 63.01, "isochromane": 134.18, "isobutylène": 56.11,
    "gaïacol": 124.14, "chlorure d'allyle": 76.52, "carbonate de potassium": 138.21,
    "dérivé de l'acide kojique": 142.11, "acétaldéhyde": 44.05, "borohydrure de sodium": 37.83,
    "benzaldéhyde": 106.12, "butan-2-one": 72.11, "dioxyde de sélénium": 110.96,
    "acide salicylique": 138.12, "acide 1-pyrroline-5-carboxylique": 113.11, "méthylglyoxal": 72.06,
    "5989-27-5": 136.23, "134-20-3": 151.16, "105-54-4": 116.16, "140-11-4": 150.17,
    "706-14-9": 170.25, "60-12-8": 122.16, "106-24-1": 154.25, "127-41-3": 192.30,
    "80-54-6": 204.31, "120-57-0": 150.13, "6790-58-5": 236.40, "54464-57-2": 234.38,
    "81-15-2": 294.30, "1222-05-5": 258.40, "97-53-0": 164.20, "4940-11-8": 140.14,
    "104-55-2": 132.16, "431-03-8": 86.09, "119-36-8": 152.15, "85228-95-9": 111.14,
}

FAST_DENSITY_MAP = {
    "5989-27-5": 0.84, "limonène": 0.84, "d-limonène": 0.84,
    "134-20-3": 1.17, "anthranilate de méthyle": 1.17,
    "105-54-4": 0.88, "butanoate d'éthyle": 0.88, "butyrate d'éthyle": 0.88,
    "140-11-4": 1.05, "acétate de benzyle": 1.05,
    "706-14-9": 0.95, "gamma-décalactone": 0.95, "γ-décalactone": 0.95,
    "60-12-8": 1.02, "alcool phényléthylique": 1.02, "2-phényléthanol": 1.02,
    "106-24-1": 0.89, "géraniol": 0.89,
    "127-41-3": 0.93, "alpha-ionone": 0.93, "α-ionone": 0.93, "ionone": 0.93,
    "80-54-6": 0.95, "lilial": 0.95,
    "120-57-0": 1.34, "héliotropine": 1.34, "pipéronal": 1.34,
    "6790-58-5": 0.96, "ambrox": 0.96, "ambroxan": 0.96,
    "54464-57-2": 0.96, "iso e super": 0.96,
    "81-15-2": 1.48, "musc cétone": 1.48,
    "1222-05-5": 1.04, "galaxolide": 1.04,
    "97-53-0": 1.06, "eugénol": 1.06,
    "4940-11-8": 1.26, "éthylmaltol": 1.26,
    "104-55-2": 1.05, "cinnamaldéhyde": 1.05,
    "431-03-8": 0.99, "diacétyle": 0.99, "butanedione": 0.99,
    "119-36-8": 1.17, "salicylate de méthyle": 1.17,
    "85228-95-9": 1.06, "2-acétyl-1-pyrroline": 1.06,
    "linalol": 0.86, "78-70-6": 0.86, "acide phosphorique": 1.88, "7664-38-2": 1.88,
    "acide anthranilique": 1.41, "118-92-3": 1.41, "méthanol": 0.79, "67-56-1": 0.79,
    "acide p-toluènesulfonique": 1.24, "104-15-4": 1.24, "acide butanoïque": 0.96, "107-92-6": 0.96,
    "éthanol": 0.79, "64-17-5": 0.79, "alcool benzylique": 1.04, "100-51-6": 1.04,
    "anhydride acétique": 1.08, "108-24-7": 1.08, "acétate de sodium": 1.53, "127-09-3": 1.53,
    "heptan-1-ol": 0.82, "111-70-6": 0.82, "acrylate de méthyle": 0.95, "96-33-3": 0.95,
    "peroxyde de di-tert-butyle": 0.80, "110-05-4": 0.80, "benzène": 0.88, "71-43-2": 0.88,
    "oxyde d'éthylène": 0.88, "75-21-8": 0.88, "trichlorure d'aluminium": 2.48, "7446-70-0": 2.48,
    "myrcène": 0.79, "123-35-3": 0.79, "acide chlorhydrique": 1.18, "7647-01-0": 1.18,
    "hydroxyde de sodium (naoh)": 2.13, "1310-73-2": 2.13, "citral": 0.89, "5392-40-5": 0.89,
    "acétone": 0.78, "67-64-1": 0.78, "trifluorure de bore éthérate": 1.12, "109-63-7": 1.12,
    "p-tert-butylbenzaldéhyde": 0.97, "939-97-9": 0.97, "propanal": 0.81, "123-38-6": 0.81,
    "isosafrole": 1.12, "120-58-1": 1.12, "ozone": 1.35, "diméthylsulfure": 0.85,
    "sclaréol": 1.01, "trichlorure de ruthénium": 3.11, "periodate de sodium": 3.86,
    "3-méthyl-3-pentèn-2-one": 0.88, "5-tert-butyl-m-xylène": 0.87, "chlorure d'acétyle": 1.10,
    "mélange nitrant (hno3 / h2so4)": 1.65, "isochromane": 1.07, "isobutylène": 0.59,
    "gaïacol": 1.13, "chlorure d'allyle": 0.94, "carbonate de potassium": 2.43,
    "dérivé de l'acide kojique": 1.45, "acétaldéhyde": 0.78, "borohydrure de sodium": 1.07,
    "benzaldéhyde": 1.04, "100-52-7": 1.04, "butan-2-one": 0.80, "dioxyde de sélénium": 3.95,
    "acide salicylique": 1.44, "acide 1-pyrroline-5-carboxylique": 1.25, "méthylglyoxal": 1.05,
}

FAST_CID_MAP = {
    "5989-27-5": 440917, "134-20-3": 8635, "105-54-4": 7762, "140-11-4": 8785,
    "706-14-9": 12813, "60-12-8": 6054, "106-24-1": 637566, "127-41-3": 638014,
    "80-54-6": 22252, "120-57-0": 8438, "6790-58-5": 643723, "54464-57-2": 108242,
    "81-15-2": 6669, "1222-05-5": 91497, "97-53-0": 3314, "4940-11-8": 21059,
    "104-55-2": 637511, "431-03-8": 650, "119-36-8": 4133, "85228-95-9": 522834,
}

GENERAL_RXN_SCHEMES = {
    "estérification de fischer": ("[*]C(=O)O.[*]O>[H+]> [*]C(=O)O[*].O", "R-COOH + R'-OH  =  R-COOR' + H2O (Catalyse acide, Delta)"),
    "substitution nucléophile acyle": ("[*]C(=O)OC(=O)[*].[*]O>>[*]C(=O)O[*].[*]C(=O)O", "Anhydride / Chlorure d'acyle + R'-OH  ->  Ester + Acide"),
    "addition radicalaire": ("[*]C(O)C.C=CC(=O)OC>[*]O.[*]> [*]C1CCC(=O)O1.CO", "Alcool secondaire + Acrylate  ->  gamma-Lactone (Initiateur radicalaire)"),
    "alkylation de friedel-crafts": ("c1ccccc1.C1CO1>Cl[Al](Cl)Cl>OCCc1ccccc1", "Ar-H + Electrophile carbone  ->  Ar-R (Acide de Lewis AlCl3 / BF3)"),
    "acylation de friedel-crafts": ("c1ccccc1.[*]C(=O)Cl>Cl[Al](Cl)Cl>[*]C(=O)c1ccccc1.Cl", "Ar-H + R-COCl  ->  Ar-CO-R + HCl (Catalyseur acide de Lewis)"),
    "addition électrophile": ("[*]C(C)=C.Cl>>[*]C(C)(Cl)C", "Alcene + H-X  ->  Derive halogene (Regle de Markovnikov)"),
    "hydrolyse": ("[*]C(=O)O[*].O>[OH-]>[*]C(=O)O.[*]O", "Ester / Halogenure + H2O  ->  Alcool + Acide"),
    "condensation aldolique": ("[*]C=O.CC(=O)[*]>[OH-]>[*]C=CC(=O)[*].O", "Aldehyde + Compose carbonyle enolisable  ->  Enone alpha,beta-insaturee + H2O"),
    "cyclisation": ("CC(C)=CCCC(C)(O)C=C>[H+]>CC1=CCC(CC1)C(=C)C.O", "Precurseur acyclique insature  ->  Carbocycle / Terpene cyclique"),
    "hydrogénation": ("[*]C=CC=O.[H][H]>[Pd]>[*]CCC=O", "Alcene alpha,beta-insature + H2  ->  Compose sature (Catalyse Pd/C)"),
    "ozonolyse": ("[*]C=C[*].O=[O+][O-]>CSC>[*]C=O.[*]C=O", "Alcene + O3  ->  Aldehydes / Cetones (Traitement reducteur Me2S)"),
    "oxydation + cyclisation": ("CC1(O)CCCC2(C)C1CCC(C)(C=C)O2>[O]>CC12CCCC(C)(C)C1CCC3(C)C2CCO3", "Clivage oxydant d'alcene suivi d'une etherification intramoleculaire"),
    "oxydation sélective": ("[*]CC(=O)[*]>O=[Se]=O>[*]C(=O)C(=O)[*].O", "Cetone enolisable + SeO2  ->  alpha-Dicetone + H2O"),
    "réaction de diels-alder": ("C=CC(=C)[*].C=CC(=O)[*]>FB(F)F>[*]C1=CCC(CC1)C(=O)[*]", "Diene conjugue + Dienophile  ->  Adduit cyclohexenique (Cycloaddition [4+2])"),
    "nitration": ("c1ccccc1.[O-][N+](=O)O>OS(=O)(=O)O>[O-][N+](=O)c1ccccc1.O", "Ar-H + HNO3  ->  Ar-NO2 + H2O (Melange sulfonitrique)"),
    "éther de williamson": ("[*]c1ccccc1O.C=CCCl>[K+].[O-]C([O-])=O>C=CCOc1ccccc1[*]", "Phenol / Alcool + R'-X  ->  Ether R-O-R' (Milieu basique K2CO3)"),
    "réarrangement de claisen": ("C=CCOc1ccccc1>>C=CCc1ccccc1O", "Ether d'allyle et de phenyle  ->  Allylphenol (Transposition [3,3] thermique)"),
    "addition nucléophile": ("O=c1cc([*])occ1O.CC=O>[BH4-].[Na+]>CC(O)c1c(O)cc([*])oc1=O", "Addition nucleophile sur aldehyde suivie d'une reduction"),
    "réduction": ("[*]C(=O)[*]>[BH4-].[Na+]>[*]C(O)[*]", "Compose carbonyle + Hydrure  ->  Alcool reduit"),
    "condensation": ("C1CC(=NCC1)C(=O)O.CC(=O)C=O>>CC(=O)C1=NCCC1.O=C=O.O", "Acide amine cyclique + alpha-Dicarbonyle  ->  Acetylpyrroline + CO2 + H2O"),
}

REACTION_DETAILS = {
    "estérification de fischer": {
        "famille": "Substitution nucléophile acyle (équilibrée)",
        "principe": "Un acide carboxylique réagit avec un alcool sous catalyse acide (H2SO4 ou APTS). La protonation du carbonyle augmente son électrophilie, permettant l'attaque nucléophile de l'alcool puis l'élimination d'une molécule d'eau.",
        "catalyseur": "Acide fort (APTS, H2SO4 ou H3PO4) en quantité catalytique (1 à 5 mol%).",
        "vigilance": "Réaction réversible limitée par l'équilibre : utiliser un excès d'alcool ou éliminer l'eau en continu (montage Dean-Stark ou tamis moléculaire 4A) pour déplacer l'équilibre vers l'ester.",
    },
    "substitution nucléophile acyle": {
        "famille": "Acylation irréversible",
        "principe": "Un dérivé d'acide activé (anhydride ou chlorure d'acyle) subit l'attaque d'un nucléophile (alcool ou amine) via un intermédiaire tétraédrique, suivie de l'expulsion du groupe partant (carboxylate ou chlorure).",
        "catalyseur": "Base douce (acétate de sodium, pyridine ou DMAP) pour piéger l'acide libéré et activer le nucléophile.",
        "vigilance": "Travailler en milieu anhydre pour éviter l'hydrolyse prématurée de l'anhydride ou du chlorure d'acyle. Contrôler l'exothermicité lors de l'addition.",
    },
    "addition radicalaire": {
        "famille": "Réaction en chaîne radicalaire",
        "principe": "Un amorceur (peroxyde) se clive thermiquement pour générer un radical qui arrache un hydrogène en alpha de l'alcool. Le radical carboné s'additionne sur l'alcène électrophile (acrylate), puis la cyclisation forme la lactone.",
        "catalyseur": "Amorceur radicalaire (peroxyde de di-tert-butyle ou AIBN) à haute température.",
        "vigilance": "Les peroxydes organiques sont thermiquement instables et comburants : ajouter l'initiateur lentement et maintenir un contrôle strict de la température sous atmosphère inerte.",
    },
    "alkylation de friedel-crafts": {
        "famille": "Substitution électrophile aromatique (SEAr)",
        "principe": "Un acide de Lewis active un électrophile carboné (époxyde, alcène ou halogénoalcane) pour générer une espèce fortement électrophile attaquée par le cycle aromatique, suivie d'une réaromatisation par perte de proton.",
        "catalyseur": "Acide de Lewis anhydre (AlCl3, BF3.OEt2 ou FeCl3).",
        "vigilance": "Sensible à l'humidité (AlCl3 s'hydrolyse violemment avec dégagement de HCl). Risque de polyalkylation : opérer souvent avec un excès du substrat aromatique et refroidir entre 0 et 10 °C.",
    },
    "acylation de friedel-crafts": {
        "famille": "Substitution électrophile aromatique (SEAr)",
        "principe": "Un chlorure d'acyle réagit avec AlCl3 pour former un ion acylium [R-C=O]+ stabilisé par résonance, qui s'additionne sur le cycle aromatique pour conduire à une cétone aromatique sans risque de polyacylation.",
        "catalyseur": "AlCl3 anhydre en quantité légèrement sur-stœchiométrique (> 1.1 éq) car il complexe la cétone formée.",
        "vigilance": "Dégagement gazeux de HCl (travailler sous sorbonne avec piège basique). Hydrolyse finale sur glace pilée + HCl dilué pour décomplexer la cétone.",
    },
    "addition électrophile": {
        "famille": "Addition sur liaison multiple C=C",
        "principe": "La liaison pi riche en électrons d'un alcène attaque un acide halogéné (H-X) pour former le carbocation le plus substitué (règle de Markovnikov), piégé ensuite par l'ion halogénure.",
        "catalyseur": "Aucun ou acide de Lewis doux selon la réactivité de l'alcène.",
        "vigilance": "Surveiller les risques de réarrangements de carbocation (transpositions) et contrôler la température pour éviter la polymérisation des terpènes conjugués.",
    },
    "hydrolyse": {
        "famille": "Clivage nucléophile par l'eau / OH-",
        "principe": "Rupture d'une liaison ester, halogénure ou éther par l'eau ou un hydroxyde (saponification), régénérant l'alcool et le carboxylate correspondant.",
        "catalyseur": "Milieu basique (NaOH, KOH) ou acide dilué à reflux.",
        "vigilance": "En milieu basique, l'acide carboxylique est obtenu sous forme de sel soluble : ne pas oublier l'acidification contrôlée lors du traitement aqueux si l'on souhaite isoler l'acide libre.",
    },
    "condensation aldolique": {
        "famille": "Formation de liaison C-C (Énolates)",
        "principe": "Une base déprotone un composé carbonylé en alpha pour former un énolate nucléophile qui attaque un aldéhyde. La bêta-hydroxycétone formée se déshydrate spontanément (crotonisation) en énone conjuguée.",
        "catalyseur": "Base aqueuse ou alcoolique (NaOH, KOH, NaOEt).",
        "vigilance": "Contrôler la température et l'ordre d'addition (souvent addition lente de l'aldéhyde) pour limiter l'auto-condensation et les polymérisations résineuses.",
    },
    "cyclisation": {
        "famille": "Addition intramoléculaire / Isomérisation",
        "principe": "Protonation d'un alcool ou d'une double liaison d'un précurseur acyclique générant un carbocation qui est piégé intramoléculairement par une seconde insaturation pour former un cycle à 6 chaînons.",
        "catalyseur": "Acide de Brønsted (H3PO4, H2SO4) ou acide de Lewis (BF3.OEt2).",
        "vigilance": "La sélectivité entre isomères (ex: alpha/bêta-ionone) dépend fortement de l'acide choisi et de la température du bain refroidissant.",
    },
    "hydrogénation": {
        "famille": "Réduction catalytique hétérogène",
        "principe": "Addition syn de dihydrogène (H2) activé à la surface d'un métal noble sur une double liaison C=C, permettant souvent une réduction sélective sans toucher la fonction carbonyle.",
        "catalyseur": "Palladium sur charbon (Pd/C 5-10%) ou Nickel de Raney.",
        "vigilance": "Risque incendie élevé : purger impérativement le réacteur à l'azote avant et après l'introduction de H2, et filtrer le catalyseur sur célite sans jamais le laisser sécher à l'air.",
    },
    "ozonolyse": {
        "famille": "Clivage oxydant d'alcène",
        "principe": "L'ozone (O3) réalise une cycloaddition dipolaire [3+2] sur l'alcène pour former un ozonide. Le traitement réducteur (Me2S) clive cet ozonide en aldéhydes ou cétones sans suroxydation en acide.",
        "catalyseur": "Générateur d'ozone à basse température (-78 °C), suivi de diméthylsulfure (Me2S) ou PPh3.",
        "vigilance": "Les ozonides intermédiaires sont explosifs à température ambiante : maintenir le refroidissement et vérifier l'absence de peroxydes (bandelette KI) avant toute évaporation.",
    },
    "oxydation + cyclisation": {
        "famille": "Séquence oxydative multi-étapes",
        "principe": "Clivage oxydant d'une chaîne latérale insaturée (système RuCl3 / NaIO4) conduisant à un intermédiaire lactone ou diol qui se cyclise ensuite en éther polycyclique stable.",
        "catalyseur": "Trichlorure de ruthénium (catalytique) régénéré par le periodate de sodium (co-oxydant).",
        "vigilance": "Système biphasique (souvent eau/acétonitrile/solvant organique) nécessitant une agitation vigoureuse pour assurer le transfert de phase.",
    },
    "oxydation sélective": {
        "famille": "Oxydation en alpha de carbonyle (Riley)",
        "principe": "Le dioxyde de sélénium (SeO2) oxyde spécifiquement un méthylène (-CH2-) en position alpha d'une cétone pour former une alpha-dicétone conjuguée.",
        "catalyseur": "SeO2 (stœchiométrique ou catalytique avec t-BuOOH).",
        "vigilance": "Les composés du sélénium sont très toxiques (SGH06/SGH08/SGH09) : manipuler sous sorbonne fermée et éliminer les résidus dans le bidon dédié aux métaux lourds.",
    },
    "réaction de diels-alder": {
        "famille": "Cycloaddition péricyclique [4+2]",
        "principe": "Réaction concertée entre un diène conjugué (4 électrons pi) et un diénophile pauvre en électrons (2 électrons pi), formant un cycle cyclohexénique avec un haut contrôle stéréochimique (règle endo).",
        "catalyseur": "Thermique ou accélérée à basse température par un acide de Lewis (BF3, AlCl3, SnCl4).",
        "vigilance": "L'utilisation d'un acide de Lewis améliore nettement la régiosélectivité mais nécessite des solvants secs et un contrôle thermique rigoureux.",
    },
    "nitration": {
        "famille": "Substitution électrophile aromatique (SEAr)",
        "principe": "Le mélange sulfonitrique génère l'ion nitronium électrophile (NO2+) qui se fixe sur le noyau aromatique pour introduire un ou plusieurs groupements nitro (-NO2).",
        "catalyseur": "Acide sulfurique concentré activant l'acide nitrique fumant.",
        "vigilance": "Réaction très exothermique et risque d'emballement thermique : maintenir strictement la température entre 0 et 15 °C pendant l'addition goutte à goutte.",
    },
    "éther de williamson": {
        "famille": "Substitution nucléophile bimoléculaire (SN2)",
        "principe": "Déprotonation d'un phénol ou d'un alcool par une base (K2CO3) pour former un phénolate/alcoolate, qui attaque un halogénure primaire ou allylique selon un mécanisme SN2.",
        "catalyseur": "Base minérale (K2CO3, NaH) en solvant polaire aprotique (acétone, DMF).",
        "vigilance": "Les halogénures allyliques (chlorure d'allyle) sont lacrymogènes, volatils et toxiques : peser et introduire impérativement sous sorbonne.",
    },
    "réarrangement de claisen": {
        "famille": "Réarrangement sigmatropique [3,3]",
        "principe": "Transposition thermique concertée d'un éther d'allyle et d'aryle vers un ortho-allylphénol via un état de transition cyclique à 6 centres, suivie d'une tautomérisation rapide.",
        "catalyseur": "Activation thermique pure (180 - 220 °C), sans catalyseur requis.",
        "vigilance": "Température élevée : opérer sous atmosphère inerte (azote/argon) pour éviter l'oxydation à l'air du phénol formé.",
    },
    "addition nucléophile": {
        "famille": "Addition sur groupement carbonyle",
        "principe": "Attaque d'un carbanion ou d'un substrat riche en électrons sur le carbone électrophile d'un aldéhyde ou d'une cétone, créant une nouvelle liaison C-C et une fonction alcool.",
        "catalyseur": "Selon le substrat : catalyse basique douce ou acide de Lewis.",
        "vigilance": "Vérifier le pH du milieu réactionnel lors du traitement final pour éviter une déshydratation non désirée de l'alcool obtenu.",
    },
    "réduction": {
        "famille": "Transfert d'hydrure (H-)",
        "principe": "Un donneur d'hydrure (NaBH4) transfère un ion H- sur le carbone électrophile d'une fonction carbonyle (aldéhyde ou cétone) pour la réduire proprement en alcool.",
        "catalyseur": "NaBH4 en milieu protique (méthanol, éthanol ou eau alcaline).",
        "vigilance": "Dégagement d'hydrogène (mousse) lors de l'hydrolyse acide finale : refroidir dans un bain de glace et ajouter l'acide lentement.",
    },
    "condensation": {
        "famille": "Condensation de Strecker / Maillard",
        "principe": "Réaction entre un acide aminé cyclique et un composé alpha-dicarbonylé entraînant une décarboxylation et la formation d'hétérocycles aromatiques azotés.",
        "catalyseur": "Activation thermique en milieu aqueux ou tamponné.",
        "vigilance": "Les composés aromatiques formés (ex: acétylpyrroline) sont très volatils et sensibles à l'oxydation : extraire rapidement et conserver au froid (-20 °C).",
    },
}

HEX_WATERMARK_SVG = (
    '<svg class="hex-watermark" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="50,6 90,28 90,72 50,94 10,72 10,28" stroke="currentColor" stroke-width="2.2"/>'
    '<circle cx="50" cy="50" r="24" stroke="currentColor" stroke-width="1.6" stroke-dasharray="5 4"/>'
    '</svg>'
)


def clean_val(val) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s.lower() in ("", "none", "nan") else s


def sanitize_filename(name: str) -> str:
    s = "".join([c for c in unicodedata.normalize("NFKD", str(name)) if not unicodedata.combining(c)])
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", s.lower())


def get_known_density(name_or_cas, fallback=1.0) -> float:
    q = clean_val(name_or_cas).lower()
    return float(FAST_DENSITY_MAP.get(q, fallback))


def export_styled_table(rows: list, columns: list, title="Export ChemBase") -> bytes:
    ths = "".join([
        f"<th style='background-color:#065f46;color:#ffffff;font-weight:bold;border:1px solid #94a3b8;padding:8px 12px;text-align:left;font-family:Consolas,monospace;font-size:12px;'>{html.escape(str(c))}</th>"
        for c in columns
    ])
    trs = []
    for idx, row in enumerate(rows):
        bg_row = "#f4f7f5" if idx % 2 == 0 else "#ffffff"
        tds = "".join([
            f"<td style='border:1px solid #cbd5e1;padding:6px 12px;background-color:{bg_row};color:#0f172a;font-family:Arial,sans-serif;font-size:12px;'>{html.escape(clean_val(row.get(c)))}</td>"
            for c in columns
        ])
        trs.append(f"<tr>{tds}</tr>")
    html_table = (
        '<html xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:x="urn:schemas-microsoft-com:office:excel" '
        'xmlns="http://www.w3.org/TR/REC-html40">'
        f'<head><meta charset="utf-8"><title>{html.escape(title)}</title></head>'
        f'<body><h3 style="font-family:Arial,sans-serif;color:#065f46;margin-bottom:4px;">CHEMBASE R&amp;D — {html.escape(title.upper())}</h3>'
        f'<p style="font-family:Consolas,monospace;font-size:11px;color:#64748b;margin-top:0;">Export du {datetime.now().strftime("%d/%m/%Y a %H:%M")}</p>'
        f'<table style="border-collapse:collapse;"><thead><tr>{ths}</tr></thead><tbody>{"".join(trs)}</tbody></table></body></html>'
    )
    return html_table.encode("utf-8-sig")


@lru_cache(maxsize=256)
def get_smiles(identifier: str):
    q = clean_val(identifier)
    if not q:
        return None
    if q.lower() in FAST_SMILES_MAP:
        return FAST_SMILES_MAP[q.lower()]
    try:
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{urllib.parse.quote(q)}/property/IsomericSMILES,CanonicalSMILES,ConnectivitySMILES/JSON"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ChemBase-App"}), timeout=5) as r:
            p = json.loads(r.read().decode("utf-8"))["PropertyTable"]["Properties"][0]
            return p.get("IsomericSMILES") or p.get("CanonicalSMILES") or p.get("ConnectivitySMILES")
    except Exception:
        return None


@lru_cache(maxsize=256)
def get_molecular_weight(identifier: str, fallback_str: str = ""):
    if fallback_str:
        m = re.search(r"(\d+(?:\.\d+)?)\s*g/mol", str(fallback_str), re.IGNORECASE)
        if m:
            return float(m.group(1))
    q = clean_val(identifier)
    if not q:
        return None
    if q.lower() in FAST_MW_MAP:
        return float(FAST_MW_MAP[q.lower()])
    try:
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{urllib.parse.quote(q)}/property/MolecularWeight/JSON"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ChemBase-App"}), timeout=5) as r:
            mw = json.loads(r.read().decode("utf-8"))["PropertyTable"]["Properties"][0].get("MolecularWeight")
            return float(mw) if mw else None
    except Exception:
        return None


@lru_cache(maxsize=256)
def get_density_from_pubchem(cas_or_name: str, cid=None):
    q = clean_val(cas_or_name).lower()
    if q in FAST_DENSITY_MAP:
        return float(FAST_DENSITY_MAP[q])
    if not cid and q:
        cid = FAST_CID_MAP.get(q)
        if not cid:
            try:
                url_c = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{urllib.parse.quote(q)}/cids/JSON"
                with urllib.request.urlopen(urllib.request.Request(url_c, headers={"User-Agent": "ChemBase-App"}), timeout=5) as rc:
                    cids = json.loads(rc.read().decode("utf-8")).get("IdentifierList", {}).get("CID", [])
                    if cids:
                        cid = cids[0]
            except Exception:
                pass
    if cid:
        try:
            url_d = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON?heading=Density"
            with urllib.request.urlopen(urllib.request.Request(url_d, headers={"User-Agent": "ChemBase-App"}), timeout=5) as rd:
                strings = re.findall(r'"String"\s*:\s*"([^"]+)"', rd.read().decode("utf-8"))
                for s in strings:
                    m_u = re.search(r"(\d+\.\d+|\d+)\s*(?:g/cm|g/ml|g/cc)", s, re.IGNORECASE)
                    if m_u and 0.4 <= float(m_u.group(1)) <= 4.5:
                        return round(float(m_u.group(1)), 2)
                for s in strings:
                    m_n = re.search(r"(\d+\.\d+)", s)
                    if m_n and 0.5 <= float(m_n.group(1)) <= 3.5:
                        return round(float(m_n.group(1)), 2)
        except Exception:
            pass
    return None


@lru_cache(maxsize=256)
def get_safety_fds_links(cas_str: str, prod_name: str = ""):
    cas_clean, prod_clean = clean_val(cas_str), clean_val(prod_name)
    q = cas_clean or prod_clean
    if not q:
        return None, None
    q_enc = urllib.parse.quote(q)
    sigma_url = f"https://www.sigmaaldrich.com/FR/fr/search/{q_enc}?focus=products&page=1&perpage=30&sort=relevance&term={q_enc}&type=product"
    cid = FAST_CID_MAP.get(cas_clean.lower())
    if not cid:
        for cand in (cas_clean, prod_clean):
            if not cand:
                continue
            try:
                url_cid = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{urllib.parse.quote(cand)}/cids/JSON"
                with urllib.request.urlopen(urllib.request.Request(url_cid, headers={"User-Agent": "ChemBase-App"}), timeout=5) as r:
                    cids = json.loads(r.read().decode("utf-8")).get("IdentifierList", {}).get("CID", [])
                    if cids:
                        cid = cids[0]
                        break
            except Exception:
                continue
    pubchem_url = f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}#datasheet=LCSS" if cid else f"https://pubchem.ncbi.nlm.nih.gov/compound/{q_enc}"
    return pubchem_url, sigma_url


def get_vector_depict_url(smiles_or_rxn: str, style="cow", w=520, h=190, zoom=2.4):
    if not smiles_or_rxn:
        return None
    return f"https://www.simolecule.com/cdkdepict/depict/{style}/svg?smi={urllib.parse.quote(smiles_or_rxn)}&abbr=on&w={w}&h={h}&zoom={zoom}"


def get_molecule_2d_url(cas_str: str, prod_name: str = "", style="cow", w=220, h=190, zoom=2.6):
    smi = get_smiles(clean_val(cas_str)) or get_smiles(clean_val(prod_name))
    if smi:
        return get_vector_depict_url(smi, style=style, w=w, h=h, zoom=zoom)
    cas = clean_val(cas_str)
    return f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{urllib.parse.quote(cas)}/PNG?image_size=500x500" if cas else None


def build_specific_reaction_smiles(row: dict):
    s1 = get_smiles(clean_val(row.get("Réactifs 1")))
    s2 = get_smiles(clean_val(row.get("Réactifs 2")))
    s3 = get_smiles(clean_val(row.get("Réactifs 3")))
    s_prod = get_smiles(clean_val(row.get("Numéro CAS"))) or get_smiles(clean_val(row.get("Produit final")))
    reactants = ".".join([s for s in (s1, s2) if s])
    return f"{reactants}>{s3 or ''}>{s_prod}" if (reactants and s_prod) else None


@lru_cache(maxsize=128)
def fetch_full_pubchem_by_cas(cas_str: str):
    cas = clean_val(cas_str)
    if not cas:
        return None
    res = {
        "titre": "", "formule": "", "etat": "", "pictos": [],
        "stockage": "", "rarete": "Courant, abordable", "densite": 1.0, "cid": None, "mw": "",
    }
    cid = None
    try:
        url_p = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{urllib.parse.quote(cas)}/property/MolecularFormula,MolecularWeight,Title/JSON"
        with urllib.request.urlopen(urllib.request.Request(url_p, headers={"User-Agent": "ChemBase-App"}), timeout=6) as r:
            p = json.loads(r.read().decode("utf-8"))["PropertyTable"]["Properties"][0]
            cid = p.get("CID")
            res["cid"] = cid
            mf, mw, title = p.get("MolecularFormula", ""), p.get("MolecularWeight", ""), p.get("Title", "")
            res["mw"] = str(mw)
            res["formule"] = f"{mf} ({mw} g/mol)" if mf and mw else mf
            res["titre"] = title
            if mw:
                mw_f = float(mw)
                res["rarete"] = (
                    "Très courant, économique" if mw_f < 160
                    else ("Intermédiaire, spécialité R&D" if mw_f < 240 else "Molécule complexe, coût élevé")
                )
    except Exception:
        return None

    dens_found = get_density_from_pubchem(cas, cid=cid) or (get_density_from_pubchem(res["titre"], cid=cid) if res["titre"] else None)
    res["densite"] = dens_found if dens_found else 1.0

    if cid:
        try:
            url_ghs = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON?heading=GHS+Classification"
            with urllib.request.urlopen(urllib.request.Request(url_ghs, headers={"User-Agent": "ChemBase-App"}), timeout=6) as rg:
                ghs_nums = sorted(set(re.findall(r"GHS0([1-9])", rg.read().decode("utf-8"))))
                res["pictos"] = [f"SGH0{n} - {SGH_DICT[f'SGH0{n}'][0]}" for n in ghs_nums if f"SGH0{n}" in SGH_DICT]
        except Exception:
            pass

        try:
            url_desc = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON?heading=Physical+Description"
            with urllib.request.urlopen(urllib.request.Request(url_desc, headers={"User-Agent": "ChemBase-App"}), timeout=6) as rd:
                raw_desc = rd.read().decode("utf-8").lower()
                etat_parts = []
                if "liquid" in raw_desc or "oil" in raw_desc:
                    etat_parts.append("Liquide")
                elif "solid" in raw_desc or "crystal" in raw_desc or "powder" in raw_desc:
                    etat_parts.append("Solide cristallin")
                elif "gas" in raw_desc:
                    etat_parts.append("Gaz")
                if "colorless" in raw_desc or "colourless" in raw_desc:
                    etat_parts.append("incolore")
                elif "white" in raw_desc:
                    etat_parts.append("blanc")
                elif "yellow" in raw_desc:
                    etat_parts.append("jaune pâle")
                base_etat = " ".join(etat_parts) if etat_parts else "Liquide ou solide"
                res["etat"] = f"{base_etat} (d = {res['densite']:.2f} g/mL)" if dens_found else base_etat
        except Exception:
            res["etat"] = f"Standard (d = {res['densite']:.2f} g/mL)" if dens_found else "Liquide ou solide standard"

        codes_only = [x.split(" - ")[0] for x in res["pictos"]]
        if "SGH01" in codes_only:
            res["stockage"] = "À l'écart de toute source de chaleur et de choc"
        elif "SGH02" in codes_only:
            res["stockage"] = "Armoire sécurité inflammables, récipient hermétique au frais"
        elif "SGH05" in codes_only:
            res["stockage"] = "Armoire ventilée anti-corrosion, flacon hermétique"
        elif "SGH06" in codes_only or "SGH08" in codes_only:
            res["stockage"] = "Armoire fermée à clé (toxiques/CMR), au sec"
        else:
            res["stockage"] = "Température ambiante (+15 à +25°C), au sec et à l'abri de la lumière"

    return res


@lru_cache(maxsize=128)
def fetch_reactant_inspector_data(reactant_name: str) -> dict:
    name = clean_val(reactant_name)
    smi = get_smiles(name)
    mw_fast = get_molecular_weight(name)
    dens_fast = get_density_from_pubchem(name)

    data = {
        "nom": name,
        "smiles": smi or "",
        "formule": "Non renseignée",
        "masse_molaire": f"{mw_fast:.2f} g/mol" if mw_fast else "N/A",
        "densite": f"{dens_fast:.2f} g/mL" if dens_fast else "N/A",
        "cas": "",
        "etat": "Consulter la FDS",
        "pictos": "",
        "cid": None,
        "iupac": "",
    }

    cid = None
    if smi:
        try:
            url_s = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/{urllib.parse.quote(smi)}/property/MolecularFormula,MolecularWeight,IUPACName/JSON"
            with urllib.request.urlopen(urllib.request.Request(url_s, headers={"User-Agent": "ChemBase-App"}), timeout=5) as rs:
                p = json.loads(rs.read().decode("utf-8"))["PropertyTable"]["Properties"][0]
                cid = p.get("CID")
                data["cid"] = cid
                if p.get("MolecularFormula"):
                    data["formule"] = p["MolecularFormula"]
                if p.get("MolecularWeight"):
                    data["masse_molaire"] = f"{float(p['MolecularWeight']):.2f} g/mol"
                if p.get("IUPACName"):
                    data["iupac"] = p["IUPACName"]
        except Exception:
            pass

    if not cid and name:
        pc_fallback = fetch_full_pubchem_by_cas(name)
        if pc_fallback:
            cid = pc_fallback.get("cid")
            data["cid"] = cid
            if pc_fallback.get("formule"):
                data["formule"] = pc_fallback["formule"].split(" (")[0]
            if pc_fallback.get("mw"):
                data["masse_molaire"] = f"{float(pc_fallback['mw']):.2f} g/mol"
            if pc_fallback.get("etat"):
                data["etat"] = pc_fallback["etat"]
            if pc_fallback.get("pictos"):
                data["pictos"] = ", ".join([x.split(" - ")[0] for x in pc_fallback["pictos"]])

    if cid:
        try:
            url_syn = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/synonyms/JSON"
            with urllib.request.urlopen(urllib.request.Request(url_syn, headers={"User-Agent": "ChemBase-App"}), timeout=4) as rsyn:
                syns = json.loads(rsyn.read().decode("utf-8"))["InformationList"]["Information"][0].get("Synonym", [])
                for syn in syns[:40]:
                    if re.fullmatch(r"\d{2,7}-\d{2}-\d", syn):
                        data["cas"] = syn
                        break
        except Exception:
            pass
        if not data["pictos"]:
            try:
                url_ghs = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON?heading=GHS+Classification"
                with urllib.request.urlopen(urllib.request.Request(url_ghs, headers={"User-Agent": "ChemBase-App"}), timeout=5) as rg:
                    ghs_nums = sorted(set(re.findall(r"GHS0([1-9])", rg.read().decode("utf-8"))))
                    data["pictos"] = ", ".join([f"SGH0{n}" for n in ghs_nums if f"SGH0{n}" in SGH_DICT])
            except Exception:
                pass
        if data["densite"] == "N/A":
            d_cid = get_density_from_pubchem(name, cid=cid)
            if d_cid:
                data["densite"] = f"{d_cid:.2f} g/mL"

    return data


def build_3dmol_html(cas_str: str, dark_mode: bool = True) -> str:
    cas = clean_val(cas_str)
    bg = "#0b1212" if dark_mode else "#ffffff"
    txt = "#94a3b8" if dark_mode else "#475569"
    if not cas:
        return f"<html><body style='margin:0;background:{bg};color:{txt};display:flex;align-items:center;justify-content:center;height:100vh;font-family:monospace;font-size:12px;'>Numéro CAS requis pour la 3D.</body></html>"
    cas_enc = urllib.parse.quote(cas)
    cas_safe = html.escape(cas)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><script src="https://3Dmol.org/build/3Dmol-min.js"></script>
<style>html,body,#v3d{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:{bg};}}</style>
</head><body>
<div id="v3d"><div id="m3d" style="position:absolute;top:46%;width:100%;text-align:center;color:{txt};font-family:monospace;font-size:12px;">Chargement 3D [CAS {cas_safe}]...</div></div>
<script>
(function(){{
  const el = document.getElementById("v3d"), msg = document.getElementById("m3d");
  const v = $3Dmol.createViewer(el, {{backgroundColor: "{bg}"}});
  const u3 = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{cas_enc}/SDF?record_type=3d";
  const u2 = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{cas_enc}/SDF";
  fetch(u3).then(r => r.ok ? r.text() : fetch(u2).then(r2 => r2.ok ? r2.text() : Promise.reject()))
    .then(sdf => {{
      if (msg) msg.style.display = "none";
      v.addModel(sdf, "sdf");
      v.setStyle({{}}, {{stick: {{radius: 0.16, colorscheme: "Jmol"}}, sphere: {{scale: 0.26, colorscheme: "Jmol"}}}});
      v.zoomTo(); v.render(); v.spin("y", 0.6);
      el.addEventListener("mousedown", () => v.spin(false));
      el.addEventListener("touchstart", () => v.spin(false));
    }})
    .catch(() => {{ if (msg) msg.innerText = "Modèle 3D indisponible pour ce CAS."; }});
}})();
</script></body></html>"""


def extract_sgh_codes(picto_str: str) -> list:
    raw = clean_val(picto_str)
    if not raw:
        return []
    valid = []
    seen = set()
    for c in [x.strip().upper() for x in raw.split(",") if x.strip()]:
        for k, (lbl, _fn) in SGH_DICT.items():
            if (k in c or lbl.lower() in c.lower()) and k not in seen:
                seen.add(k)
                valid.append((k, lbl))
                break
    return valid


def render_pictograms_html(picto_str: str) -> str:
    raw = clean_val(picto_str)
    if not raw:
        return '<span class="muted-small">Aucun danger majeur classé</span>'
    valid = extract_sgh_codes(raw)
    if not valid:
        return f'<span class="mono-tag">{html.escape(raw)}</span>'
    items = []
    for code, lbl in valid:
        svg_markup = SGH_SVG_MAP.get(code, "")
        items.append(
            f'<div class="sgh-item" title="{html.escape(code + " — " + lbl)}">'
            f"{svg_markup}"
            f"<span>{code}</span></div>"
        )
    return f'<div class="sgh-row">{"".join(items)}</div>'


def generate_bottle_label_html(
    nom: str,
    cas: str = "",
    formule: str = "",
    pictos: str = "",
    stockage: str = "",
    operateur: str = "chercheur",
    date_str: str = "",
    lot_info: str = "",
) -> str:
    """Page prête à imprimer avec étiquette de flacon normée SGH (et repères de découpe)."""
    nom_s = html.escape(clean_val(nom) or "Substance")
    cas_s = html.escape(clean_val(cas) or "Non renseigné")
    form_s = html.escape(clean_val(formule) or "—")
    stock_s = html.escape(clean_val(stockage) or "Température ambiante, au sec")
    op_s = html.escape(clean_val(operateur) or "chercheur")
    dt_s = html.escape(clean_val(date_str) or datetime.now().strftime("%d/%m/%Y"))
    lot_s = html.escape(clean_val(lot_info) or f"CB-{datetime.now().strftime('%y%m%d')}")

    valid_sgh = extract_sgh_codes(pictos)
    if valid_sgh:
        sgh_block = "".join([
            f'<div class="picto-box">{SGH_SVG_MAP[c]}<span>{c} · {html.escape(lbl)}</span></div>'
            for c, lbl in valid_sgh
        ])
        signal_word = (
            "DANGER"
            if any(c in ("SGH01", "SGH02", "SGH05", "SGH06", "SGH08") for c, _ in valid_sgh)
            else "ATTENTION"
        )
        signal_cls = "sig-danger" if signal_word == "DANGER" else "sig-warn"
    else:
        sgh_block = '<div class="no-sgh">Aucun pictogramme SGH majeur classé</div>'
        signal_word = "USAGE LABO"
        signal_cls = "sig-safe"

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><title>Étiquette Flacon — {nom_s}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #eef2f3; margin: 0; padding: 28px; color: #0f172a; }}
  .toolbar {{ max-width: 110mm; margin: 0 auto 18px auto; display: flex; justify-content: space-between; align-items: center; gap: 10px; }}
  .print-btn {{ background: #059669; color: #fff; border: none; border-radius: 8px; padding: 9px 16px; font-weight: 700; cursor: pointer; font-size: 13px; }}
  .print-btn:hover {{ background: #047857; }}
  .hint {{ font-size: 12px; color: #475569; }}
  .sheet {{ display: flex; flex-direction: column; gap: 10mm; align-items: center; }}
  .label-card {{
    width: 105mm; min-height: 62mm; background: #ffffff;
    border: 1.5px dashed #94a3b8; padding: 4.5mm 5.5mm;
    display: flex; flex-direction: column; justify-content: space-between;
    box-shadow: 0 6px 20px rgba(0,0,0,0.08);
  }}
  .top-row {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; border-bottom: 1.6px solid #0f172a; padding-bottom: 3mm; }}
  .brand {{ font-family: Consolas, monospace; font-size: 8.5px; letter-spacing: 0.1em; color: #059669; font-weight: 700; }}
  .title {{ font-size: 16px; font-weight: 800; margin: 2px 0 1px 0; line-height: 1.15; }}
  .sub {{ font-family: Consolas, monospace; font-size: 10px; color: #334155; }}
  .sig {{ font-family: Consolas, monospace; font-size: 10px; font-weight: 800; padding: 3px 7px; border-radius: 4px; letter-spacing: 0.08em; }}
  .sig-danger {{ background: #dc2626; color: #fff; }}
  .sig-warn {{ background: #d97706; color: #fff; }}
  .sig-safe {{ background: #059669; color: #fff; }}
  .pictos {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; padding: 3mm 0; }}
  .picto-box {{ display: inline-flex; flex-direction: column; align-items: center; gap: 2px; }}
  .picto-box svg {{ width: 34px; height: 34px; }}
  .picto-box span {{ font-size: 7.5px; font-family: Consolas, monospace; color: #334155; }}
  .no-sgh {{ font-size: 10px; color: #475569; font-style: italic; }}
  .meta {{ border-top: 1px solid #cbd5e1; padding-top: 2.5mm; font-size: 9.5px; line-height: 1.45; }}
  .meta-row {{ display: flex; justify-content: space-between; gap: 8px; font-family: Consolas, monospace; font-size: 8.8px; color: #334155; margin-top: 3px; }}
  @media print {{
    body {{ background: #fff; padding: 4mm; }}
    .toolbar {{ display: none !important; }}
    .label-card {{ box-shadow: none; break-inside: avoid; }}
  }}
</style></head>
<body>
  <div class="toolbar">
    <span class="hint">Format 105 × 62 mm · Repères de découpe inclus</span>
    <button class="print-btn" onclick="window.print()">Imprimer / Enregistrer en PDF</button>
  </div>
  <div class="sheet">
    <div class="label-card">
      <div class="top-row">
        <div>
          <div class="brand">CHEMBASE R&amp;D · ÉTIQUETTE FLACON</div>
          <div class="title">{nom_s}</div>
          <div class="sub">CAS : {cas_s} · {form_s}</div>
        </div>
        <span class="sig {signal_cls}">{signal_word}</span>
      </div>
      <div class="pictos">{sgh_block}</div>
      <div class="meta">
        <div><strong>Stockage :</strong> {stock_s}</div>
        <div class="meta-row">
          <span>Lot : {lot_s}</span>
          <span>Opérateur : {op_s}</span>
          <span>Date : {dt_s}</span>
        </div>
      </div>
    </div>
  </div>
</body></html>"""


def generate_labo_entry_html(entry: dict) -> str:
    """Fiche de paillasse imprimable / PDF pour un essai du Cahier de Laboratoire."""
    prod = html.escape(clean_val(entry.get("produit_cible")) or "Essai")
    dt = html.escape(clean_val(entry.get("date_essai")) or "N/A")
    op = html.escape(clean_val(entry.get("operateur")) or "chercheur")
    st = html.escape(clean_val(entry.get("statut")) or "N/A")
    qtes = html.escape(clean_val(entry.get("quantites_engagees")) or "Non précisé")
    mt = float(entry.get("masse_theorique") or 0.0)
    mo = float(entry.get("masse_obtenue") or 0.0)
    rdt = float(entry.get("rendement_reel") or 0.0)
    rdt_ref = html.escape(clean_val(entry.get("rendement_theorique")) or "N/A")
    obs = html.escape(clean_val(entry.get("observations")) or "Aucune observation complémentaire.")
    eid = entry.get("id", "—")

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><title>Essai #{eid} — {prod}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 36px; color: #0f172a; background: #f4f7f6; }}
  .toolbar {{ max-width: 780px; margin: 0 auto 14px auto; text-align: right; }}
  .print-btn {{ background: #059669; color: #fff; border: none; border-radius: 8px; padding: 9px 16px; font-weight: 700; cursor: pointer; }}
  .sheet {{ max-width: 780px; margin: 0 auto; background: #fff; border: 1px solid #cbd5e1; border-radius: 10px; padding: 34px; }}
  h1 {{ color: #059669; font-size: 1.15rem; letter-spacing: 0.06em; text-transform: uppercase; border-bottom: 2px solid #059669; padding-bottom: 8px; margin: 0 0 12px 0; }}
  h2 {{ margin: 0 0 16px 0; font-size: 1.5rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 18px; }}
  .box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px 12px; }}
  .lbl {{ font-family: Consolas, monospace; font-size: 10px; text-transform: uppercase; color: #64748b; }}
  .val {{ font-size: 15px; font-weight: 700; margin-top: 3px; }}
  .sec {{ background: #f8fafc; border-left: 3px solid #059669; padding: 14px 16px; border-radius: 6px; margin-bottom: 14px; }}
  .sec h3 {{ margin: 0 0 6px 0; font-size: 0.9rem; color: #059669; text-transform: uppercase; font-family: Consolas, monospace; }}
  .foot {{ margin-top: 28px; padding-top: 10px; border-top: 1px solid #e2e8f0; font-family: Consolas, monospace; font-size: 11px; color: #64748b; display: flex; justify-content: space-between; }}
  @media print {{
    body {{ background: #fff; margin: 0; }}
    .toolbar {{ display: none !important; }}
    .sheet {{ border: none; padding: 10mm; max-width: 100%; }}
  }}
</style></head>
<body>
  <div class="toolbar"><button class="print-btn" onclick="window.print()">Imprimer / Enregistrer en PDF</button></div>
  <div class="sheet">
    <h1>ChemBase R&amp;D — Feuille de Paillasse (Essai #{eid})</h1>
    <h2>{prod}</h2>
    <div class="grid">
      <div class="box"><div class="lbl">Date</div><div class="val">{dt}</div></div>
      <div class="box"><div class="lbl">Opérateur</div><div class="val">{op}</div></div>
      <div class="box"><div class="lbl">Statut</div><div class="val">{st}</div></div>
      <div class="box"><div class="lbl">Masse théorique</div><div class="val">{mt:.2f} g</div></div>
      <div class="box"><div class="lbl">Masse obtenue</div><div class="val">{mo:.2f} g</div></div>
      <div class="box"><div class="lbl">Rendement réel (Réf : {rdt_ref})</div><div class="val" style="color:#059669;">{rdt:.1f} %</div></div>
    </div>
    <div class="sec"><h3>Quantités engagées</h3><p style="margin:0;line-height:1.6;">{qtes}</p></div>
    <div class="sec"><h3>Observations, Analyses &amp; Notes</h3><p style="margin:0;line-height:1.6;white-space:pre-wrap;">{obs}</p></div>
    <div class="foot"><span>CHEMBASE CAHIER DE LABORATOIRE</span><span>Exporté le {datetime.now().strftime("%d/%m/%Y à %H:%M")}</span></div>
  </div>
</body></html>"""


def generate_molecule_html(row: dict) -> bytes:
    prod = clean_val(row.get("Produit final")) or "Molécule"
    cas = clean_val(row.get("Numéro CAS"))
    dens_val = get_density_from_pubchem(cas) or get_density_from_pubchem(prod)
    dens_str = f"{dens_val:.2f} g/mL" if dens_val else "N/A"
    rx1, rx2 = clean_val(row.get("Réaction 1")), clean_val(row.get("Réaction 2"))
    reas = [clean_val(row.get(f"Réactifs {i}")) for i in range(1, 5) if clean_val(row.get(f"Réactifs {i}"))]
    rx_html = f'<span class="badge">{html.escape(rx1)}</span>' + (f' &rarr; <span class="badge">{html.escape(rx2)}</span>' if rx2 else "")
    comm = clean_val(row.get("Commentaire"))
    img_2d = get_molecule_2d_url(cas, prod, style="cow", w=240, h=200, zoom=2.6)
    rxn_smi = build_specific_reaction_smiles(row)
    rxn_svg_url = get_vector_depict_url(rxn_smi, style="cow", w=600, h=180, zoom=2.4) if rxn_smi else None
    pc_url, sig_url = get_safety_fds_links(cas, prod)
    fds_links_html = f'<p class="no-print" style="margin-top:12px;"><strong>FDS Officielles :</strong> <a href="{pc_url}" target="_blank" style="color:#059669;margin-right:15px;">PubChem (LCSS) &nearr;</a> <a href="{sig_url}" target="_blank" style="color:#059669;">Sigma-Aldrich (Merck) &nearr;</a></p>' if pc_url else ""
    img_tag = f'<img src="{img_2d}" alt="2D" style="float:right;width:160px;border:1px solid #cbd5e1;border-radius:8px;background:white;padding:6px;margin-left:15px;">' if img_2d else ""
    rxn_block = f'<div style="background:white;border:1px solid #cbd5e1;border-radius:8px;padding:10px;text-align:center;margin-top:12px;"><img src="{rxn_svg_url}" style="max-width:100%;height:auto;"></div>' if rxn_svg_url else ""
    valid_sgh = extract_sgh_codes(clean_val(row.get("Pictogrammes danger")))
    sgh_svgs = "".join([f'<span style="display:inline-flex;flex-direction:column;align-items:center;margin-right:8px;">{SGH_SVG_MAP[c]}<small style="font-family:monospace;font-size:9px;">{c}</small></span>' for c, _ in valid_sgh])
    sgh_line = f'<div style="display:flex;align-items:center;flex-wrap:wrap;margin-top:8px;">{sgh_svgs}</div>' if sgh_svgs else "Aucun"
    doc = f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>Fiche - {html.escape(prod)}</title>
    <style>
      body{{font-family:'Helvetica Neue',Arial,sans-serif;margin:36px;color:#0f172a;background:#f4f7f6}}
      .toolbar{{max-width:820px;margin:0 auto 14px auto;text-align:right}}
      .print-btn{{background:#059669;color:#fff;border:none;border-radius:8px;padding:9px 16px;font-weight:700;cursor:pointer}}
      .container{{max-width:820px;margin:0 auto;background:white;padding:38px;border-radius:10px;border:1px solid #d5e0dc}}
      h1{{color:#059669;border-bottom:2px solid #059669;padding-bottom:10px;margin-top:0;font-size:1.3rem;letter-spacing:0.04em;text-transform:uppercase}}
      .badge{{background:#ecfdf5;color:#059669;border:1px solid #059669;padding:4px 10px;border-radius:4px;font-size:0.85rem;font-weight:600;display:inline-block}}
      .section{{margin-top:22px;padding:18px;background:#f8fafc;border-radius:6px;border-left:3px solid #059669;overflow:hidden}}
      .sgh-svg{{width:34px;height:34px}}
      .footer{{margin-top:34px;text-align:center;font-size:0.78rem;color:#64748b;border-top:1px solid #e2e8f0;padding-top:10px;font-family:monospace}}
      @media print{{body{{background:#fff;margin:0}}.toolbar,.no-print{{display:none!important}}.container{{border:none;padding:8mm;max-width:100%}}}}
    </style></head>
    <body>
      <div class="toolbar"><button class="print-btn" onclick="window.print()">Imprimer / Enregistrer en PDF</button></div>
      <div class="container">
        <h1>ChemBase R&amp;D — Spécification Technique</h1>
        <h2>{html.escape(prod)} {f"<span style='font-family:monospace;font-size:1rem;color:#64748b;'>[CAS {html.escape(cas)}]</span>" if cas else ""}</h2>
        <div class="section"><h3>01 / Paramètres &amp; Équation de Réaction</h3><p><strong>Voie principale :</strong> {rx_html}</p><p><strong>Réactifs :</strong> {html.escape(", ".join(reas) or "N/A")}</p><p><strong>Rendement de référence :</strong> {html.escape(clean_val(row.get("Rendement")) or "N/A")}</p><p><strong>Conditions opératoires :</strong> {html.escape(clean_val(row.get("Conditions opératoires")) or "N/A")}</p>{f"<p><strong>Notes :</strong> {html.escape(comm)}</p>" if comm else ""}{rxn_block}</div>
        <div class="section">{img_tag}<h3>02 / Propriétés Physico-Chimiques &amp; Sécurité</h3><p><strong>Formule &amp; Masse :</strong> {html.escape(clean_val(row.get("Formule brute & masse")) or "N/A")}</p><p><strong>Densité :</strong> {dens_str}</p><p><strong>État physique :</strong> {html.escape(clean_val(row.get("État physique")) or "N/A")}</p><p><strong>Classification SGH :</strong></p>{sgh_line}<p><strong>Disponibilité :</strong> {html.escape(clean_val(row.get("Rareté & Coût")) or "N/A")}</p><p><strong>Stockage :</strong> {html.escape(clean_val(row.get("Conditions de stockage")) or "N/A")}</p>{fds_links_html}</div>
        <div class="footer">CHEMBASE R&amp;D SYSTEM — EXPORT DU {datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
      </div>
    </body></html>"""
    return doc.encode("utf-8")
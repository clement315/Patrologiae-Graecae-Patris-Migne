"""
Split a merged PG volume into its individual works and structure each of them.

    python pg_works.py --vol 94 --model .../best_0.9885.safetensors
    (normally:  bash pg_ocr.sh 94 works)

Steps
  1. Page order.  Some stretches of the main scan are out of order and contain re-scanned
     pages (PG 94: the Dialectica, PDF pp. 297-344).  The second scan is in the right
     order, so every page is placed by the leaf of the second scan it was matched to;
     two pages matched to the same leaf are the same page scanned twice (one is dropped).
  2. Coverage check.  Every leaf of the second scan that carries Greek text must be covered
     by a page of the volume; uncovered leaves are listed (a page missing from the main scan).
  3. Migne columns from the running heads of both scans, fitted in the corrected order.
  4. Each work (table WORKS) is structured according to its kind:
       books     books and numbered chapters (Expositio fidei)
       chapters  numbered chapters, one book (Dialectica)
       sections  titled sections, not numbered (De haeresibus, Contra Jacobitas, ...)
       orations  orations from the running heads, titled sections inside (De imaginibus)
       numbered  sections numbered in the text ('βʹ. Σκυθισμός') (De haeresibus, Contra Jacobitas)
       dialogue  speaker turns (MAN. / ORTH.) start new paragraphs (numbered_dialogue: also numbered)

Outputs: output/PG094/works/<work>/<work>.md, sections/NNN.txt, report.txt;
         output/PG094/works/works.tsv, coverage.txt
"""
import argparse
import collections
import gzip
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pg_structure as S  # noqa: E402

VERSION = "1.33"

WORKS = {
    25: [
        # S. Athanasius, Opera, pars I (historica et dogmatica).  "col": first Migne column
        # (Ordo rerum and running heads of the Oxford copy, checked on the page images); the
        # Latin Monita between the works are left out (work/PG025/exclude_pages.txt).
        # The chapter numerals (Αʹ., Βʹ., ...) are printed in small capitals and read too
        # unreliably to number the chapters: the works are kept as running text.
        {"slug": "contra_gentes", "title": "Oratio contra gentes", "col": 3, "pages": [295, 341],
         "kind": "sections"},
        {"slug": "de_incarnatione", "title": "Oratio de incarnatione Verbi", "col": 95, "pages": [341, 396],
         "kind": "sections", "cut": True},
        {"slug": "expositio_fidei", "title": "Expositio fidei", "col": 199, "pages": [397, 401], "kind": "sections"},
        {"slug": "in_illud_omnia_mihi_tradita", "title": "In illud: Omnia mihi tradita sunt (Mt 11:27)",
         "col": 209, "pages": [402, 407], "kind": "sections"},
        {"slug": "epistola_encyclica", "title": "Epistola encyclica ad episcopos", "col": 221, "pages": [408, 417],
         "kind": "sections"},
        {"slug": "apologia_contra_arianos", "title": "Apologia contra Arianos (Apologia secunda)", "col": 247,
         "pages": [421, 504], "kind": "sections"},
        {"slug": "de_decretis", "title": "De decretis Nicaenae synodi", "col": 415, "pages": [507, 541],
         "kind": "sections"},
        {"slug": "de_sententia_dionysii", "title": "De sententia Dionysii", "col": 479, "pages": [543, 566],
         "kind": "sections"},
        {"slug": "epistola_ad_dracontium", "title": "Epistola ad Dracontium", "col": 523, "pages": [567, 574],
         "kind": "sections"},
        {"slug": "ad_episcopos_aegypti_et_libyae", "title": "Epistola encyclica ad episcopos Aegypti et Libyae",
         "col": 537, "pages": [576, 604], "kind": "sections"},
        {"slug": "apologia_ad_constantium", "title": "Apologia ad Constantium imperatorem", "col": 595,
         "pages": [605, 642], "kind": "sections"},
        # p643: Latin Admonitio, then the Greek title and the first lines of the text
        {"slug": "apologia_de_fuga", "title": "Apologia de fuga sua", "col": 643, "pages": [643, 661],
         "kind": "sections"},
        {"slug": "de_morte_arii", "title": "Epistola ad Serapionem de morte Arii", "col": 685, "pages": [664, 666],
         "kind": "sections"},
        {"slug": "epistola_ad_monachos", "title": "Epistola ad monachos", "col": 691, "pages": [667, 668],
         "kind": "sections"},
        {"slug": "historia_arianorum", "title": "Historia Arianorum ad monachos", "col": 695, "pages": [669, 719],
         "kind": "sections"},
    ],
    26: [
        # S. Athanasius, Opera, pars I (cont.) and pars II.  "col": first Migne column (running
        # heads of the scan: left column = 2p - 15 up to p258, 2p - 35 from p269, after the ten
        # pages the scan contains twice); Latin-only works and Monita are excluded
        # (work/PG026/exclude_pages.txt): De Trinitate et Spiritu sancto, Ep. II ad Luciferum,
        # the Latin version of the Epistolae heortasticae.  Kept as running text with the
        # titled sections the layout model finds (the numerals are not read reliably).
        {"slug": "oratio_1_contra_arianos", "title": "Oratio I contra Arianos", "col": 11, "pages": [13, 80],
         "kind": "sections", "cut": True},
        {"slug": "oratio_2_contra_arianos", "title": "Oratio II contra Arianos", "col": 145, "pages": [80, 167],
         "kind": "sections", "cut": True},
        {"slug": "oratio_3_contra_arianos", "title": "Oratio III contra Arianos", "col": 321, "pages": [168, 241],
         "kind": "sections"},
        {"slug": "oratio_4_contra_arianos", "title": "Oratio IV contra Arianos", "col": 468, "pages": [241, 280],
         "kind": "sections", "cut": True},
        {"slug": "epistolae_ad_serapionem", "title": "Epistolae IV ad Serapionem", "col": 529, "pages": [282, 355],
         "kind": "sections"},
        {"slug": "de_synodis", "title": "Epistola de synodis Arimini et Seleuciae", "col": 681, "pages": [358, 414],
         "kind": "sections"},
        {"slug": "tomus_ad_antiochenos", "title": "Tomus ad Antiochenos", "col": 796, "pages": [415, 422],
         "kind": "sections"},
        {"slug": "epistola_ad_jovianum", "title": "Epistola ad Jovianum imperatorem (with the Petitiones Arianorum)",
         "col": 813, "pages": [424, 429], "kind": "sections"},
        {"slug": "vita_antonii", "title": "Vita S. Antonii", "col": 837, "pages": [436, 505], "kind": "sections"},
        {"slug": "ad_orsisium_et_ammonium", "title": "Epistolae II ad Orsisium; Narratio ad Ammonium", "col": 977,
         "pages": [505, 508], "kind": "sections", "cut": True},
        {"slug": "de_incarnatione_et_contra_arianos", "title": "De incarnatione Verbi et contra Arianos",
         "col": 983, "pages": [509, 531], "kind": "sections"},
        {"slug": "epistola_ad_afros", "title": "Epistola ad Afros episcopos", "col": 1029, "pages": [532, 541],
         "kind": "sections"},
        {"slug": "epistola_ad_epictetum", "title": "Epistola ad Epictetum", "col": 1049, "pages": [542, 552],
         "kind": "sections"},
        {"slug": "epistola_ad_adelphium", "title": "Epistola ad Adelphium", "col": 1072, "pages": [553, 559],
         "kind": "sections"},
        {"slug": "epistola_ad_maximum", "title": "Epistola ad Maximum philosophum", "col": 1085, "pages": [560, 562],
         "kind": "sections"},
        {"slug": "contra_apollinarium_1", "title": "Contra Apollinarium liber I", "col": 1093, "pages": [564, 583],
         "kind": "sections"},
        {"slug": "contra_apollinarium_2", "title": "Contra Apollinarium liber II", "col": 1131, "pages": [583, 600],
         "kind": "sections", "cut": True},
        {"slug": "epistolae_minores", "title": "Epistolae minores (ad Amunem, ep. heort. XXXIX fragm., ad Rufinianum, "
         "ad Luciferum I, ad monachos)", "col": 1165, "pages": [600, 611], "kind": "sections", "cut": True},
        {"slug": "fragmenta_varia", "title": "Fragmenta varia", "col": 1217, "pages": [626, 647], "kind": "sections"},
        {"slug": "sermo_maior_de_fide", "title": "Sermo maior de fide (with the pieces printed after it)", "col": 1265,
         "pages": [650, 665], "kind": "sections"},
        {"slug": "sermones_varii", "title": "Sermones et fragmenta (de patientia, in ramos palmarum, contra "
         "Macedonianos, contra Novatianos, de amuletis, de azymis)", "col": 1297, "pages": [666, 683],
         "kind": "sections"},
        {"slug": "epistolae_heortasticae_graece", "title": "Epistolae heortasticae: fragmenta Graeca", "col": 1433,
         "pages": [734, 739], "kind": "sections"},
    ],
    27: [
        # S. Athanasius, Opera, pars III (exegetica).  "col": first Migne column (running heads:
        # left column = 2p - 11 before the copy pp. 53-54, 2p - 15 up to p522, 2p - 35 after
        # the copy pp. 523-532, 2p - 55 after the copy pp. 673-682)
        {"slug": "epistola_ad_marcellinum", "title": "Epistola ad Marcellinum in interpretationem Psalmorum",
         "col": 11, "pages": [11, 28], "kind": "sections"},
        {"slug": "expositiones_in_psalmos", "title": "Argumentum in Psalmos; Expositiones in Psalmos", "col": 55,
         "pages": [33, 281], "kind": "sections"},
        {"slug": "fragmenta_in_psalmos", "title": "Fragmenta commentarii in Psalmos", "col": 547,
         "pages": [281, 302], "kind": "sections", "cut": True},
        # Greek lemmata with Latin in the same lines on many pages (lower confidence there)
        {"slug": "de_titulis_psalmorum", "title": "De titulis Psalmorum (ed. Antonelli)", "col": 647,
         "pages": [331, 699], "kind": "sections"},
        {"slug": "fragmenta_exegetica", "title": "Fragmenta exegetica (in Job, in Cantica, in Matthaeum, in Lucam, "
         "in I ad Corinthios)", "col": 1345, "pages": [700, 731], "kind": "sections"},
    ],
    28: [
        # S. Athanasius, Opera, pars IV (dubia et spuria).  Works from the running heads of the
        # scan and the titles the layout model finds; "col": left column of the first page
        # (2p - 15 before, 2p - 19 after the copy pp. 407-408); Latin-only pieces excluded
        # (work/PG028/exclude_pages.txt).  A work starting under a title in mid-page is "cut".
        {"slug": "de_incarnatione_dei_verbi", "title": "De incarnatione Dei Verbi", "col": 25, "pages": [20, 21], "kind": "sections", "cut": True},
        {"slug": "de_communi_essentia", "title": "De communi essentia Patris et Filii et Spiritus sancti", "col": 29, "pages": [22, 46], "kind": "sections", "cut": True},
        {"slug": "epistola_catholica", "title": "Epistola catholica", "col": 79, "pages": [47, 49], "kind": "sections", "cut": True},
        {"slug": "refutatio_hypocriseos_meletii", "title": "Refutatio hypocriseos Meletii et Eusebii", "col": 85, "pages": [50, 51], "kind": "sections"},
        {"slug": "de_incarnatione_2", "title": "De incarnatione Dei Verbi (second piece in the running heads)", "col": 89, "pages": [52, 54], "kind": "sections", "cut": True},
        {"slug": "contra_sabellianos", "title": "Contra Sabellianos", "col": 95, "pages": [55, 67], "kind": "sections", "cut": True},
        {"slug": "quod_unus_sit_christus", "title": "Quod unus sit Christus", "col": 121, "pages": [68, 73], "kind": "sections", "cut": True},
        {"slug": "de_sabbatis_et_circumcisione", "title": "De sabbatis et circumcisione", "col": 133, "pages": [74, 78], "kind": "sections", "cut": True},
        {"slug": "homilia_de_semente", "title": "Homilia de semente", "col": 143, "pages": [79, 91], "kind": "sections", "cut": True},
        {"slug": "in_illud_profecti_in_pagum", "title": "In illud: Profecti in pagum", "col": 169, "pages": [92, 99], "kind": "sections"},
        {"slug": "de_passione_et_cruce", "title": "De passione et cruce Domini", "col": 185, "pages": [100, 132], "kind": "sections", "cut": True},
        {"slug": "de_virginitate", "title": "De virginitate", "col": 251, "pages": [13, 79], "kind": "sections", "cut": True},
        {"slug": "synopsis_scripturae", "title": "Synopsis Scripturae sacrae", "col": 281, "pages": [148, 226], "kind": "sections", "cut": True},
        {"slug": "disputatio_contra_arium", "title": "Disputatio contra Arium (in concilio Nicaeno)", "col": 439, "pages": [227, 257], "kind": "sections", "cut": True},
        {"slug": "sermo_contra_omnes_haereses", "title": "Sermo contra omnes haereses", "col": 501, "pages": [258, 269], "kind": "sections", "cut": True},
        {"slug": "historia_de_melchisedech", "title": "Historia de Melchisedech", "col": 525, "pages": [270, 273], "kind": "sections", "cut": True},
        {"slug": "liber_de_definitionibus", "title": "Liber de definitionibus", "col": 533, "pages": [274, 282], "kind": "sections", "cut": True},
        {"slug": "doctrina_ad_antiochum", "title": "Doctrina ad Antiochum ducem", "col": 551, "pages": [283, 301], "kind": "sections", "cut": True},
        {"slug": "quaestiones_ad_antiochum", "title": "Quaestiones ad Antiochum ducem", "col": 589, "pages": [302, 361], "kind": "sections", "cut": True},
        {"slug": "quaestiones_aliae", "title": "Quaestiones in Scripturam, in N. T., in Psalmos, in epistolas Pauli, aliae", "col": 709, "pages": [362, 405], "kind": "sections"},
        {"slug": "de_miraculo_beryti", "title": "De miraculo Beryti (imago Christi)", "col": 797, "pages": [406, 411], "kind": "sections"},
        {"slug": "de_passione_imaginis", "title": "De passione imaginis D. N. Jesu Christi", "col": 805, "pages": [412, 415], "kind": "sections", "cut": True},
        {"slug": "sermo_contra_latinos", "title": "Sermo contra Latinos", "col": 823, "pages": [421, 424], "kind": "sections", "cut": True},
        {"slug": "syntagma_doctrinae", "title": "Syntagma doctrinae (ad monachos)", "col": 831, "pages": [425, 433], "kind": "sections", "cut": True},
        {"slug": "epistolae_ad_castorem", "title": "Epistolae ad Castorem", "col": 849, "pages": [434, 461], "kind": "sections", "cut": True},
        {"slug": "in_nativitatem_praecursoris", "title": "Homilia in nativitatem Praecursoris", "col": 905, "pages": [462, 465], "kind": "sections", "cut": True},
        {"slug": "in_annuntiationem", "title": "Sermo in annuntiationem Deiparae", "col": 913, "pages": [466, 479], "kind": "sections"},
        {"slug": "de_descriptione_deiparae", "title": "Sermo de descriptione Deiparae", "col": 943, "pages": [481, 488], "kind": "sections"},
        {"slug": "in_nativitatem_christi", "title": "Sermo in nativitatem Christi", "col": 959, "pages": [489, 495], "kind": "sections"},
        {"slug": "in_occursum_domini", "title": "Homilia in occursum Domini", "col": 973, "pages": [496, 509], "kind": "sections", "cut": True},
        {"slug": "in_caecum_a_nativitate", "title": "Homilia in caecum a nativitate", "col": 1001, "pages": [510, 520], "kind": "sections", "cut": True},
        {"slug": "in_illud_euntes_in_castellum", "title": "Homilia in illud: Euntes in castellum", "col": 1023, "pages": [521, 532], "kind": "sections", "cut": True},
        {"slug": "in_feriam_quartam", "title": "Sermo in feriam IV", "col": 1047, "pages": [533, 535], "kind": "sections", "cut": True},
        {"slug": "in_passionem_domini", "title": "Sermo in passionem Domini", "col": 1053, "pages": [536, 539], "kind": "sections", "cut": True},
        {"slug": "in_patres_et_prophetas", "title": "Homilia in SS. Patres et prophetas", "col": 1061, "pages": [540, 545], "kind": "sections", "cut": True},
        {"slug": "in_sanctum_pascha", "title": "Sermo in sanctum Pascha", "col": 1073, "pages": [546, 554], "kind": "sections", "cut": True},
        {"slug": "in_assumptionem_domini", "title": "Sermo in assumptionem Domini", "col": 1091, "pages": [555, 559], "kind": "sections", "cut": True},
        {"slug": "in_andream_et_exhortatorius", "title": "Encomium in S. Andream; Sermo exhortatorius", "col": 1101, "pages": [560, 565], "kind": "sections"},
        {"slug": "de_trinitate_dialogi", "title": "De sancta Trinitate dialogi V", "col": 1113, "pages": [566, 653], "kind": "sections", "cut": True},
        {"slug": "contra_macedonianos_dialogi", "title": "Contra Macedonianos dialogi II", "col": 1289, "pages": [654, 677], "kind": "sections"},
        {"slug": "confutationes_propositionum", "title": "Confutationes quarumdam propositionum", "col": 1337, "pages": [678, 709], "kind": "sections", "cut": True},
        {"slug": "syntagma_ad_politicum", "title": "Syntagma ad quemdam politicum", "col": 1401, "pages": [710, 713], "kind": "sections", "cut": True},
        {"slug": "sermo_pro_renuntiantibus", "title": "Sermo pro iis qui saeculo renuntiarunt", "col": 1409, "pages": [714, 719], "kind": "sections", "cut": True},
        {"slug": "doctrina_ad_monachos", "title": "Doctrina ad monachos", "col": 1421, "pages": [720, 726], "kind": "sections"},
        {"slug": "epistolae_liberii_athanasii", "title": "Epistolae Liberii et Athanasii (Greek)", "col": 1441, "pages": [730, 731], "kind": "sections"},
        {"slug": "vita_syncleticae", "title": "Vita S. Syncleticae", "col": 1487, "pages": [753, 787], "kind": "sections"},
        {"slug": "epistola_ad_episcopum_persarum", "title": "Epistola ad episcopum Persarum", "col": 1557, "pages": [788, 793], "kind": "sections", "cut": True},
        {"slug": "symbolum_quicumque", "title": "Symbolum Quicumque (Greek forms)", "col": 1581, "pages": [800, 810], "kind": "sections"},
        {"slug": "de_ratione_paschali", "title": "De ratione Paschali; fragmenta", "col": 1603, "pages": [811, 812], "kind": "sections", "cut": True},
        {"slug": "addenda", "title": "Addenda", "col": 1637, "pages": [828, 831], "kind": "sections"},
    ],
    29: [
        # S. Basilius, Opera, tomus I.  "col": first Migne column (running heads: left column =
        # 2p - 823, from p693 2p - 843 after the copy pp. 683-692).  The Greek Acoluthia triplicis
        # festi and Historia institutionis in the Prolegomena (pp. 341-411, Roman column numbers)
        # are in the merged text but not split as works.
        {"slug": "hexaemeron", "title": "Homiliae IX in Hexaemeron", "col": 3, "pages": [413, 515],
         "kind": "sections"},
        {"slug": "homiliae_in_psalmos", "title": "Homiliae in Psalmos", "col": 209, "pages": [516, 658],
         "kind": "sections"},
        {"slug": "adversus_eunomium", "title": "Adversus Eunomium libri V (IV-V dubii)", "col": 497,
         "pages": [660, 808], "kind": "sections"},
    ],
    30: [
        # S. Basilius, Appendix tomi I (opera dubia et spuria) and Eunomius' Apologia.  Main scan:
        # IA PatrologiaGraeca, Vol. 030 (a Google scan); "col": left column = 2p - 9 (cols. 715-718
        # and 803-806 are missing in the scan, see SCAN_FIXES).
        {"slug": "de_hominis_structura_et_de_paradiso", "title": "De hominis structura orationes I-II; De paradiso oratio",
         "col": 11, "pages": [10, 39], "kind": "sections"},
        {"slug": "homiliae_in_psalmos_spuriae", "title": "Homiliae in Psalmos (spuriae)", "col": 71, "pages": [40, 62],
         "kind": "sections", "cut": True},
        {"slug": "commentarius_in_isaiam", "title": "Enarratio in prophetam Isaiam (dubia)", "col": 117,
         "pages": [63, 338], "kind": "sections"},
        {"slug": "de_virginitate", "title": "De vera virginitate (ad Letoium)", "col": 669, "pages": [339, 405],
         "kind": "sections"},
        {"slug": "sermo_de_contubernalibus", "title": "Sermo de contubernalibus", "col": 809, "pages": [405, 414],
         "kind": "sections", "cut": True},
        {"slug": "eunomii_apologia", "title": "Eunomius, Liber apologeticus", "col": 835, "pages": [418, 434],
         "kind": "sections", "cut": True},
    ],
    31: [
        # S. Basilius, tomus II: Homiliae et sermones, Ascetica, Appendix.  Main scan: IA
        # patrologiae_cursus_completus_gr_vol_031 (Google ZhfZAAAAMAA).  "col": first column from the
        # volume's index (Ordo rerum, PDF pp. 938-940) and the Greek titles in the IA OCR; running heads:
        # left column = 2p - 17 (pp. 90-399), 2p - 21 (402-575), 2p - 25 (578-629), 2p - 29 (632-817),
        # 2p - 33 (820-877); the steps are the four pairs of pages photographed twice (SCAN_FIXES).
        # Latin-only pieces (Liturgia Coptica, De consolatione in adversis, ...) are excluded pages.
        {"slug": "hom_01_de_jejunio_1", "title": "Homilia I de jejunio", "col": 163, "pages": [90, 101], "kind": "sections"},
        {"slug": "hom_02_de_jejunio_2", "title": "Homilia II de jejunio", "col": 185, "pages": [101, 107], "kind": "sections", "cut": True},
        {"slug": "hom_03_attende_tibi_ipsi", "title": "Homilia III in illud: Attende tibi ipsi", "col": 197, "pages": [107, 117], "kind": "sections", "cut": True},
        {"slug": "hom_04_de_gratiarum_actione", "title": "Homilia IV de gratiarum actione", "col": 217, "pages": [117, 127], "kind": "sections", "cut": True},
        {"slug": "hom_05_in_julittam", "title": "Homilia V in martyrem Julittam", "col": 237, "pages": [127, 139], "kind": "sections", "cut": True},
        {"slug": "hom_06_destruam_horrea", "title": "Homilia VI in illud Lucae: Destruam horrea mea", "col": 261, "pages": [139, 147], "kind": "sections", "cut": True},
        {"slug": "hom_07_in_divites", "title": "Homilia VII in divites", "col": 277, "pages": [147, 160], "kind": "sections", "cut": True},
        {"slug": "hom_08_in_famem", "title": "Homilia VIII dicta tempore famis et siccitatis", "col": 304, "pages": [160, 173], "kind": "sections", "cut": True},
        {"slug": "hom_09_deus_non_auctor_malorum", "title": "Homilia IX quod Deus non est auctor malorum", "col": 329, "pages": [173, 185], "kind": "sections", "cut": True},
        {"slug": "hom_10_adversus_iratos", "title": "Homilia X adversus eos qui irascuntur", "col": 353, "pages": [185, 194], "kind": "sections", "cut": True},
        {"slug": "hom_11_de_invidia", "title": "Homilia XI de invidia", "col": 372, "pages": [194, 201], "kind": "sections", "cut": True},
        {"slug": "hom_12_in_principium_proverbiorum", "title": "Homilia XII in principium Proverbiorum", "col": 385, "pages": [201, 220], "kind": "sections", "cut": True},
        {"slug": "hom_13_exhortatoria_ad_baptismum", "title": "Homilia XIII exhortatoria ad sanctum baptisma", "col": 424, "pages": [220, 230], "kind": "sections", "cut": True},
        {"slug": "hom_14_in_ebriosos", "title": "Homilia XIV in ebriosos", "col": 444, "pages": [230, 240], "kind": "sections", "cut": True},
        {"slug": "hom_15_de_fide", "title": "Homilia XV de fide", "col": 464, "pages": [240, 244], "kind": "sections", "cut": True},
        {"slug": "hom_16_in_principio_erat_verbum", "title": "Homilia XVI in illud: In principio erat Verbum", "col": 472, "pages": [244, 250], "kind": "sections", "cut": True},
        {"slug": "hom_17_in_barlaam", "title": "Homilia XVII in Barlaam martyrem", "col": 484, "pages": [250, 253], "kind": "sections", "cut": True},
        {"slug": "hom_18_in_gordium", "title": "Homilia XVIII in Gordium martyrem", "col": 489, "pages": [253, 262], "kind": "sections", "cut": True},
        {"slug": "hom_19_in_quadraginta_martyres", "title": "Homilia XIX in sanctos quadraginta martyres", "col": 508, "pages": [262, 271], "kind": "sections", "cut": True},
        {"slug": "hom_20_de_humilitate", "title": "Homilia XX de humilitate", "col": 525, "pages": [271, 278], "kind": "sections", "cut": True},
        {"slug": "hom_21_quod_rebus_mundanis", "title": "Homilia XXI quod rebus mundanis adhaerendum non sit", "col": 540, "pages": [278, 290], "kind": "sections", "cut": True},
        {"slug": "hom_22_ad_adolescentes", "title": "Homilia XXII ad adolescentes (de legendis libris gentilium)", "col": 564, "pages": [290, 303], "kind": "sections", "cut": True},
        {"slug": "hom_23_in_mamantem", "title": "Homilia XXIII in sanctum martyrem Mamantem", "col": 589, "pages": [303, 308], "kind": "sections", "cut": True},
        {"slug": "hom_24_contra_sabellianos", "title": "Homilia XXIV contra Sabellianos, Arium et Anomoeos", "col": 600, "pages": [308, 318], "kind": "sections", "cut": True},
        {"slug": "praevia_institutio_ascetica", "title": "Praevia institutio ascetica", "col": 619, "pages": [318, 321], "kind": "sections", "cut": True},
        {"slug": "sermo_de_renuntiatione_saeculi", "title": "Sermo asceticus et exhortatio de renuntiatione saeculi", "col": 625, "pages": [321, 332], "kind": "sections", "cut": True},
        {"slug": "sermo_de_ascetica_disciplina", "title": "Sermo de ascetica disciplina", "col": 648, "pages": [332, 335], "kind": "sections", "cut": True},
        {"slug": "prooemium_de_judicio_dei", "title": "Prooemium de judicio Dei", "col": 653, "pages": [335, 346], "kind": "sections", "cut": True},
        {"slug": "de_fide", "title": "De fide", "col": 676, "pages": [346, 354], "kind": "sections", "cut": True},
        {"slug": "moralia", "title": "Moralia (with the index of the rules)", "col": 691, "pages": [354, 445], "kind": "sections", "cut": True},
        {"slug": "sermones_ascetici", "title": "Sermones ascetici I-II", "col": 869, "pages": [445, 455], "kind": "sections", "cut": True},
        {"slug": "regulae_fusius_tractatae", "title": "Regulae fusius tractatae", "col": 889, "pages": [455, 536], "kind": "sections", "cut": True},
        {"slug": "regulae_brevius_tractatae", "title": "Regulae brevius tractatae (with the index of the rules)", "col": 1051, "pages": [536, 667], "kind": "sections", "cut": True},
        {"slug": "poenae_et_epitimia", "title": "Poenae in monachos delinquentes; Epitimia in canonicas", "col": 1305, "pages": [667, 672], "kind": "sections", "cut": True},
        {"slug": "constitutiones_monasticae", "title": "Constitutiones monasticae (with the index of the chapters)", "col": 1315, "pages": [672, 728], "kind": "sections", "cut": True},
        {"slug": "app_de_spiritu_sancto", "title": "Appendix: Homilia de Spiritu sancto", "col": 1429, "pages": [729, 733], "kind": "sections", "cut": True},
        {"slug": "app_in_lacizis", "title": "Appendix: Homilia dicta in Lacizis", "col": 1437, "pages": [733, 743], "kind": "sections", "cut": True},
        {"slug": "app_in_christi_generationem", "title": "Appendix: Homilia in sanctam Christi generationem", "col": 1457, "pages": [743, 752], "kind": "sections", "cut": True},
        {"slug": "app_de_poenitentia", "title": "Appendix: Homilia de poenitentia", "col": 1475, "pages": [752, 758], "kind": "sections", "cut": True},
        {"slug": "app_adversus_calumniatores", "title": "Appendix: Homilia adversus eos qui per calumniam dicunt dici a nobis deos tres", "col": 1487, "pages": [758, 763], "kind": "sections", "cut": True},
        {"slug": "app_ne_dederis_somnum", "title": "Appendix: Homilia in illud: Ne dederis somnum oculis tuis, and the piece after it", "col": 1497, "pages": [763, 771], "kind": "sections", "cut": True},
        {"slug": "de_baptismo", "title": "De baptismo libri II", "col": 1513, "pages": [771, 831], "kind": "sections", "cut": True},
        {"slug": "liturgia_alexandrina", "title": "Liturgia S. Basilii Alexandrina", "col": 1629, "pages": [831, 844], "kind": "sections", "cut": True},
        {"slug": "orationes_sive_exorcismi", "title": "Orationes sive exorcismi", "col": 1679, "pages": [856, 859], "kind": "sections", "cut": True},
        {"slug": "sermo_de_sacerdotum_institutione", "title": "Sermo de sacerdotum institutione; Precatio altera", "col": 1685, "pages": [859, 860], "kind": "sections", "cut": True},
        {"slug": "de_misericordia_et_judicio", "title": "De misericordia et judicio", "col": 1705, "pages": [869, 873], "kind": "sections", "cut": True},
        {"slug": "homilia_consolatoria_ad_aegrotum", "title": "Homilia consolatoria ad aegrotum", "col": 1713, "pages": [873, 877], "kind": "sections", "cut": True},
    ],
    32: [
        # S. Basilius, tomus III: De Spiritu sancto, Epistolae (classes I-III, ep. 1-366), Appendix:
        # Symeon Metaphrastes, Sermones XXIV ex Basilio.  Main scan: IA patrologiae_cursus_completus_gr_vol_032.
        # Running heads: left column = 2p - 11 (pp. 39-198), 2p - 15 (201-264), 2p - 19 (267-372),
        # 2p - 23 (375-638), 2p - 27 (641-704); the steps are the four pairs of pages photographed twice.
        {"slug": "de_spiritu_sancto", "title": "De Spiritu sancto (ad Amphilochium)", "col": 67, "pages": [39, 114], "kind": "sections"},
        {"slug": "epistolae", "title": "Epistolae I-CCCLXVI (classes I-III)", "col": 219, "pages": [115, 567], "kind": "sections"},
        {"slug": "symeon_metaphrastes_sermones", "title": "Appendix: Symeon Metaphrastes, Sermones XXIV de moribus ex Basilio",
         "col": 1115, "pages": [569, 704], "kind": "sections"},
    ],
    33: [
        # S. Cyrillus Hierosolymitanus; Petrus II and Timotheus Alexandrini; Apollinaris; Diodorus Tarsensis.
        # Main scan: IA patrologiae_cursus_completus_gr_vol_033.  Running heads: left column = 2p - 11
        # (pp. 152-360), 2p - 15 (363-564), 2p - 19 (567-596), 2p - 23 (599-826); the steps are the three
        # pairs of pages photographed twice.  Touttee's Dissertationes, Milles' preface and notes, the
        # Descriptio ecclesiae Hierosolymitanae and the Latin notices are excluded pages.
        {"slug": "testimonia_veterum", "title": "Cyrillus: Veterum testimonia; tituli catecheseon", "col": 293, "pages": [152, 170], "kind": "sections"},
        {"slug": "procatechesis", "title": "Cyrillus: Procatechesis", "col": 331, "pages": [171, 190], "kind": "sections", "cut": True},
        {"slug": "catecheses_i_xviii", "title": "Cyrillus: Catecheses illuminandorum I-XVIII", "col": 369, "pages": [190, 540], "kind": "sections", "cut": True},
        {"slug": "catecheses_mystagogicae", "title": "Cyrillus: Catecheses mystagogicae I-V", "col": 1065, "pages": [540, 575], "kind": "sections", "cut": True},
        {"slug": "homilia_in_paralyticum", "title": "Cyrillus: Homilia in paralyticum", "col": 1131, "pages": [575, 592], "kind": "sections", "cut": True},
        {"slug": "epistola_ad_constantium_et_fragmenta", "title": "Cyrillus: Epistola ad Constantium imperatorem; Fragmenta", "col": 1165, "pages": [592, 605], "kind": "sections", "cut": True},
        {"slug": "homilia_in_occursum_domini", "title": "Appendix: Homilia in occursum Domini (incerti)", "col": 1187, "pages": [605, 614], "kind": "sections", "cut": True},
        {"slug": "epistola_ad_augustinum_spuria", "title": "Appendix: Epistola ad Augustinum (spuria)", "col": 1205, "pages": [614, 616], "kind": "sections", "cut": True},
        {"slug": "petrus_ii_alexandrinus", "title": "Petrus II Alexandrinus: Epistola encyclica et alia", "col": 1275, "pages": [649, 657], "kind": "sections"},
        {"slug": "timotheus_alexandrinus", "title": "Timotheus Alexandrinus: Responsa canonica; Epistola", "col": 1295, "pages": [659, 665], "kind": "sections"},
        {"slug": "apollinaris_metaphrasis_psalmorum", "title": "Apollinaris Laodicenus: Metaphrasis Psalmorum", "col": 1313, "pages": [668, 784], "kind": "sections"},
        {"slug": "diodorus_tarsensis_fragmenta", "title": "Diodorus Tarsensis: Fragmenta (in Genesin, in Psalmos, ...); Addenda", "col": 1553, "pages": [788, 826], "kind": "sections"},
    ],
    35: [
        # S. Gregorius Nazianzenus I: Vita (auctore Gregorio presbytero); Orationes I-XXVI.  Main scan: IA
        # patrologiae_cursus_completus_gr_vol_035.  Running heads: left column = 2p - 19 (pp. 131-360), 2p - 23
        # (363-368), 2p - 27 (371-639); the steps are the two pairs of pages photographed twice.
        {"slug": "vita_gregorii", "title": "Vita S. Gregorii Theologi, auctore Gregorio presbytero", "col": 243, "pages": [131, 160], "kind": "sections"},
        {"slug": "oratio_01", "title": "Oratio I: In sanctum Pascha et in tarditatem", "col": 395, "pages": [207, 213], "kind": "sections"},
        {"slug": "oratio_02", "title": "Oratio II: Apologetica (de fuga)", "col": 407, "pages": [213, 268], "kind": "sections", "cut": True},
        {"slug": "oratio_03", "title": "Oratio III: Ad eos qui ipsum acciverant nec occurrerant", "col": 517, "pages": [268, 275], "kind": "sections", "cut": True},
        {"slug": "oratio_04", "title": "Oratio IV: Contra Julianum I", "col": 531, "pages": [275, 341], "kind": "sections", "cut": True},
        {"slug": "oratio_05", "title": "Oratio V: Contra Julianum II", "col": 664, "pages": [341, 374], "kind": "sections", "cut": True},
        {"slug": "oratio_06", "title": "Oratio VI: De pace I", "col": 721, "pages": [374, 391], "kind": "sections", "cut": True},
        {"slug": "oratio_07", "title": "Oratio VII: In laudem Caesarii fratris", "col": 755, "pages": [391, 408], "kind": "sections", "cut": True},
        {"slug": "oratio_08", "title": "Oratio VIII: In laudem sororis Gorgoniae", "col": 789, "pages": [408, 423], "kind": "sections", "cut": True},
        {"slug": "oratio_09", "title": "Oratio IX: Apologetica ad patrem", "col": 819, "pages": [423, 427], "kind": "sections", "cut": True},
        {"slug": "oratio_10", "title": "Oratio X: In seipsum, post reditum", "col": 828, "pages": [427, 429], "kind": "sections", "cut": True},
        {"slug": "oratio_11", "title": "Oratio XI: Ad Gregorium Nyssenum", "col": 832, "pages": [429, 435], "kind": "sections", "cut": True},
        {"slug": "oratio_12", "title": "Oratio XII: Ad patrem, cum ei curam ecclesiae commisisset", "col": 844, "pages": [435, 439], "kind": "sections", "cut": True},
        {"slug": "oratio_13", "title": "Oratio XIII: In consecratione Eulalii Doarensis", "col": 852, "pages": [439, 442], "kind": "sections", "cut": True},
        {"slug": "oratio_14", "title": "Oratio XIV: De pauperum amore", "col": 857, "pages": [442, 469], "kind": "sections", "cut": True},
        {"slug": "oratio_15", "title": "Oratio XV: In laudem Machabaeorum", "col": 912, "pages": [469, 480], "kind": "sections", "cut": True},
        {"slug": "oratio_16", "title": "Oratio XVI: In patrem tacentem propter plagam grandinis", "col": 933, "pages": [480, 495], "kind": "sections", "cut": True},
        {"slug": "oratio_17", "title": "Oratio XVII: Ad cives Nazianzenos et praefectum irascentem", "col": 964, "pages": [495, 506], "kind": "sections", "cut": True},
        {"slug": "oratio_18", "title": "Oratio XVIII: Funebris in patrem", "col": 985, "pages": [506, 535], "kind": "sections", "cut": True},
        {"slug": "oratio_19", "title": "Oratio XIX: Ad Julianum tributorum exaequatorem", "col": 1044, "pages": [535, 546], "kind": "sections", "cut": True},
        {"slug": "oratio_20", "title": "Oratio XX: De dogmate et constitutione episcoporum", "col": 1065, "pages": [546, 554], "kind": "sections", "cut": True},
        {"slug": "oratio_21", "title": "Oratio XXI: In laudem Athanasii", "col": 1081, "pages": [554, 579], "kind": "sections", "cut": True},
        {"slug": "oratio_22", "title": "Oratio XXII: De pace II", "col": 1132, "pages": [579, 589], "kind": "sections", "cut": True},
        {"slug": "oratio_23", "title": "Oratio XXIII: De pace III", "col": 1152, "pages": [589, 598], "kind": "sections", "cut": True},
        {"slug": "oratio_24", "title": "Oratio XXIV: In laudem Cypriani", "col": 1169, "pages": [598, 612], "kind": "sections", "cut": True},
        {"slug": "oratio_25", "title": "Oratio XXV: In laudem Heronis philosophi", "col": 1197, "pages": [612, 627], "kind": "sections", "cut": True},
        {"slug": "oratio_26", "title": "Oratio XXVI: In seipsum, cum rure rediisset", "col": 1228, "pages": [627, 639], "kind": "sections", "cut": True},
    ],
    36: [
        # S. Gregorius Nazianzenus II: Orationes XXVII-XLV; opuscula; liturgiae; commentators (Elias Cretensis,
        # Nicetas Serronius, Nonnus abbas, Basilius Minimus, scholia anonyma).  Main scan: IA
        # patrologiae_cursus_completus_gr_vol_036.  Running heads: left column = 2p - 9 (pp. 9-37), 2p - 29 (48-189),
        # 2p - 49 (200-507), 2p - 69 (518-665); the steps are three blocks of ten pages photographed twice
        # (pp. 38-47 = 28-37, 190-199 = 180-189, 508-517 = 498-507), left out in work/PG036/exclude_pages.txt.
        {"slug": "oratio_27", "title": "Oratio XXVII: Theologica I: Adversus Eunomianos", "col": 12, "pages": [10, 17], "kind": "sections"},
        {"slug": "oratio_28", "title": "Oratio XXVIII: Theologica II: De theologia", "col": 25, "pages": [17, 51], "kind": "sections", "cut": True},
        {"slug": "oratio_29", "title": "Oratio XXIX: Theologica III: De Filio I", "col": 73, "pages": [51, 66], "kind": "sections", "cut": True},
        {"slug": "oratio_30", "title": "Oratio XXX: Theologica IV: De Filio II", "col": 104, "pages": [66, 81], "kind": "sections", "cut": True},
        {"slug": "oratio_31", "title": "Oratio XXXI: Theologica V: De Spiritu sancto", "col": 133, "pages": [81, 101], "kind": "sections", "cut": True},
        {"slug": "oratio_32", "title": "Oratio XXXII: De moderatione in disputando", "col": 173, "pages": [101, 121], "kind": "sections", "cut": True},
        {"slug": "oratio_33", "title": "Oratio XXXIII: Contra Arianos et de seipso", "col": 213, "pages": [121, 135], "kind": "sections", "cut": True},
        {"slug": "oratio_34", "title": "Oratio XXXIV: In Aegyptiorum adventum", "col": 241, "pages": [135, 143], "kind": "sections", "cut": True},
        {"slug": "oratio_35", "title": "Oratio XXXV: In martyres et adversus Arianos (spuria)", "col": 257, "pages": [143, 147], "kind": "sections", "cut": True},
        {"slug": "oratio_36", "title": "Oratio XXXVI: De seipso et ad eos qui ipsum cathedram Constantinopolitanam affectare dicebant", "col": 265, "pages": [147, 155], "kind": "sections", "cut": True},
        {"slug": "oratio_37", "title": "Oratio XXXVII: In dictum Evangelii: Cum consummasset Jesus hos sermones", "col": 281, "pages": [155, 170], "kind": "sections", "cut": True},
        {"slug": "oratio_38", "title": "Oratio XXXVIII: In Theophania (In Natalem Salvatoris)", "col": 312, "pages": [170, 182], "kind": "sections", "cut": True},
        {"slug": "oratio_39", "title": "Oratio XXXIX: In sancta Lumina", "col": 336, "pages": [182, 204], "kind": "sections", "cut": True},
        {"slug": "oratio_40", "title": "Oratio XL: In sanctum Baptisma", "col": 360, "pages": [204, 238], "kind": "sections", "cut": True},
        {"slug": "oratio_41", "title": "Oratio XLI: In Pentecosten", "col": 428, "pages": [238, 253], "kind": "sections", "cut": True},
        {"slug": "oratio_42", "title": "Oratio XLII: Supremum vale (coram 150 episcopis)", "col": 457, "pages": [253, 271], "kind": "sections", "cut": True},
        {"slug": "oratio_43", "title": "Oratio XLIII: Funebris in laudem Basilii Magni", "col": 493, "pages": [271, 328], "kind": "sections", "cut": True},
        {"slug": "oratio_44", "title": "Oratio XLIV: In novam Dominicam", "col": 608, "pages": [328, 336], "kind": "sections", "cut": True},
        {"slug": "oratio_45", "title": "Oratio XLV: In sanctum Pascha", "col": 624, "pages": [336, 356], "kind": "sections", "cut": True},
        {"slug": "opuscula_appendix", "title": "Significatio in Ezechielem; De fide orthodoxa (spuria); Fragmentum ex oratione contra astronomos", "col": 665, "pages": [357, 362], "kind": "sections", "cut": True},
        {"slug": "liturgiae", "title": "Liturgia S. Gregorii Coptica (Greek parts) et Alexandrina; Precatio et exorcismus", "col": 677, "pages": [363, 391], "kind": "sections"},
        {"slug": "elias_cretensis_commentarii", "title": "Elias Cretensis: Commentarii in XIX orationes S. Gregorii (with addenda)", "col": 757, "pages": [403, 475], "kind": "sections"},
        {"slug": "scholia_varia", "title": "Scholia in S. Gregorii orationes (Basilius?)", "col": 903, "pages": [476, 482], "kind": "sections"},
        {"slug": "nicetas_serronius_commentarii", "title": "Nicetas Serronius: Commentarii in orationes S. Gregorii (with notice)", "col": 933, "pages": [491, 526], "kind": "sections"},
        {"slug": "nonnus_abbas", "title": "Nonnus abbas: Collectio et expositio historiarum in orationes S. Gregorii", "col": 985, "pages": [527, 570], "kind": "sections"},
        {"slug": "basilius_minimus_scholia", "title": "Basilius Minimus: Scholia in orationes S. Gregorii", "col": 1073, "pages": [571, 636], "kind": "sections"},
        {"slug": "scholia_anonyma_in_julianum", "title": "Anonymi scholia in orationes contra Julianum", "col": 1205, "pages": [637, 665], "kind": "sections"},
    ],
    37: [
        # S. Gregorius Nazianzenus III: Epistolae; Testamentum; Carmina, liber I (theologica: dogmatica,
        # moralia) and liber II (historica: de seipso, quae spectant ad alios).  Main scan: IA
        # patrologiae_cursus_completus_gr_vol_037, in order with no repeated pages.  Running heads: left
        # column = 2p - 11 (pp. 16-805).  Pp. 1-15 (title, Latin prefaces) and 806-811 (Latin index) are
        # excluded pages.  P. 266 holds the end of I.1.38 (left) and the title of I.2.1 (right): kept whole
        # in the dogmatica, the moralia begin with p. 267.
        {"slug": "epistolae", "title": "Epistolae (I-CCXLIX, with the Epistolae theologicae)", "col": 21, "pages": [16, 199], "kind": "sections"},
        {"slug": "testamentum", "title": "Testamentum", "col": 389, "pages": [200, 203], "kind": "sections"},
        {"slug": "carmina_dogmatica", "title": "Carmina, liber I, sectio I: Poemata dogmatica", "col": 397, "pages": [204, 266], "kind": "sections"},
        {"slug": "carmina_moralia", "title": "Carmina, liber I, sectio II: Poemata moralia", "col": 523, "pages": [267, 489], "kind": "sections"},
        {"slug": "carmina_de_seipso", "title": "Carmina, liber II, sectio I: Poemata de seipso", "col": 969, "pages": [490, 730], "kind": "sections"},
        {"slug": "carmina_ad_alios", "title": "Carmina, liber II, sectio II: Poemata quae spectant ad alios", "col": 1451, "pages": [731, 805], "kind": "sections"},
    ],
    38: [
        # S. Gregorius Nazianzenus IV: Carmina II.2 (epitaphia, epigrammata); Christus patiens (appendix);
        # Cosmas Hierosolymitanus, Nicetas David and an anonymous paraphrast on the Carmina; S. Caesarius
        # (Pseudo-Caesarius), Dialogi IV.  Main scan: IA patrologiae_cursus_completus_gr_vol_038, in order
        # with no repeated pages.  Running heads: left column = 2p - 11 (pp. 10-600).  Excluded pages: 1-9
        # (title pages), the Latin notices pp. 71, 175, 346, 429-430, and the indexes pp. 601-657.
        {"slug": "epitaphia_et_epigrammata", "title": "Carmina, liber II, sectio II (cont.): Epitaphia; Epigrammata", "col": 9, "pages": [10, 70], "kind": "sections"},
        {"slug": "christus_patiens", "title": "Appendix: Christus patiens (tragoedia)", "col": 133, "pages": [72, 174], "kind": "sections"},
        {"slug": "cosmas_hierosolymitanus_commentarii", "title": "Cosmas Hierosolymitanus: Collectio et expositio historiarum in carmina S. Gregorii (with index)", "col": 341, "pages": [176, 345], "kind": "sections"},
        {"slug": "nicetas_david_paraphrasis", "title": "Nicetas David: Paraphrasis carminum arcanorum S. Gregorii (with an anonymous paraphrasis)", "col": 683, "pages": [347, 428], "kind": "sections"},
        {"slug": "caesarius_dialogi", "title": "S. Caesarius (Pseudo-Caesarius): Dialogi IV (Quaestiones et responsiones)", "col": 851, "pages": [431, 600], "kind": "sections"},
    ],
    44: [
        # S. Gregorius Nyssenus I: exegetical works.  Main scan: IA patrologiae_cursus_completus_gr_vol_044.
        # Running heads: left column = 2p - 15 (pp. 38-258), 2p - 35 (269-689); pp. 259-268 are a second copy of
        # pp. 249-258 (In inscriptiones Psalmorum), photographed twice, left out in work/PG044/exclude_pages.txt.
        # Excluded too: pp. 1-37 (title pages, Latin prolegomena) and 690-727 (Variorum notae, indexes).
        {"slug": "hexaemeron", "title": "Apologia in Hexaemeron", "col": 61, "pages": [38, 69], "kind": "sections"},
        {"slug": "de_hominis_opificio", "title": "De hominis opificio (with Nicetas' epigram)", "col": 123, "pages": [69, 135], "kind": "sections", "cut": True},
        {"slug": "in_verba_faciamus_hominem", "title": "In verba: Faciamus hominem ad imaginem et similitudinem nostram, orationes II (dubiae)", "col": 257, "pages": [136, 156], "kind": "sections"},
        {"slug": "de_vita_moysis", "title": "De vita Moysis", "col": 297, "pages": [156, 222], "kind": "sections", "cut": True},
        {"slug": "in_inscriptiones_psalmorum", "title": "In inscriptiones Psalmorum", "col": 431, "pages": [223, 321], "kind": "sections"},
        {"slug": "in_sextum_psalmum", "title": "In sextum Psalmum, pro octava", "col": 607, "pages": [321, 325], "kind": "sections", "cut": True},
        {"slug": "in_ecclesiasten", "title": "In Ecclesiasten homiliae VIII", "col": 616, "pages": [325, 394], "kind": "sections", "cut": True},
        {"slug": "in_canticum_canticorum", "title": "In Canticum canticorum homiliae XV", "col": 755, "pages": [395, 577], "kind": "sections"},
        {"slug": "de_oratione_dominica", "title": "De oratione dominica orationes V", "col": 1119, "pages": [577, 614], "kind": "sections", "cut": True},
        {"slug": "de_beatitudinibus", "title": "De beatitudinibus orationes VIII", "col": 1193, "pages": [614, 668], "kind": "sections", "cut": True},
        {"slug": "in_illud_tunc_et_ipse_filius", "title": "In illud: Tunc et ipse Filius subjicietur (1 Cor 15:28)", "col": 1303, "pages": [669, 680], "kind": "sections"},
        {"slug": "de_eo_quid_sit_ad_imaginem", "title": "Appendix: De eo quid sit ad imaginem Dei et ad similitudinem (dubium)", "col": 1327, "pages": [681, 689], "kind": "sections"},
    ],
    45: [
        # S. Gregorius Nyssenus II: dogmatic works.  Main scan: IA patrologiae_cursus_completus_gr_vol_045, in
        # order with no repeated pages.  Running heads: left column = 2p - 15 (pp. 12-674).  Excluded pages: 1-11
        # (title pages) and 675-689 (Variorum notae, index).  Contra Eunomium in Migne's twelve books plus
        # liber XIIb (= book II in Jaeger's edition, against Eunomius' second Apology); each book with its
        # list of chapters.
        {"slug": "oratio_catechetica", "title": "Oratio catechetica magna", "col": 9, "pages": [12, 61], "kind": "sections"},
        {"slug": "de_pythonissa", "title": "De pythonissa (De engastrimytho), ad Theodosium episcopum", "col": 107, "pages": [61, 65], "kind": "sections", "cut": True},
        {"slug": "ad_ablabium_quod_non_sint_tres_dii", "title": "Ad Ablabium, quod non sint tres dii", "col": 115, "pages": [65, 75], "kind": "sections", "cut": True},
        {"slug": "ad_simplicium_de_fide", "title": "Ad Simplicium, de fide", "col": 135, "pages": [75, 80], "kind": "sections", "cut": True},
        {"slug": "contra_fatum", "title": "Contra fatum", "col": 145, "pages": [80, 95], "kind": "sections", "cut": True},
        {"slug": "ad_graecos_ex_communibus_notionibus", "title": "Ad Graecos, ex communibus notionibus", "col": 175, "pages": [95, 101], "kind": "sections", "cut": True},
        {"slug": "de_anima", "title": "De anima (dubium)", "col": 187, "pages": [101, 118], "kind": "sections", "cut": True},
        {"slug": "epistola_canonica_ad_letoium", "title": "Epistola canonica ad Letoium Melitenes episcopum", "col": 221, "pages": [118, 125], "kind": "sections", "cut": True},
        {"slug": "epistolae_ad_petrum", "title": "Contra Eunomium: Gregory's letter to Peter of Sebaste and Peter's reply", "col": 237, "pages": [126, 129], "kind": "sections"},
        {"slug": "contra_eunomium_i", "title": "Contra Eunomium, liber I (Migne's numbering)", "col": 243, "pages": [129, 239], "kind": "sections", "cut": True},
        {"slug": "contra_eunomium_ii", "title": "Contra Eunomium, liber II (Migne's numbering)", "col": 463, "pages": [239, 293], "kind": "sections", "cut": True},
        {"slug": "contra_eunomium_iii", "title": "Contra Eunomium, liber III (Migne's numbering)", "col": 571, "pages": [293, 315], "kind": "sections", "cut": True},
        {"slug": "contra_eunomium_iv", "title": "Contra Eunomium, liber IV (Migne's numbering)", "col": 615, "pages": [315, 346], "kind": "sections", "cut": True},
        {"slug": "contra_eunomium_v", "title": "Contra Eunomium, liber V (Migne's numbering)", "col": 677, "pages": [346, 362], "kind": "sections", "cut": True},
        {"slug": "contra_eunomium_vi", "title": "Contra Eunomium, liber VI (Migne's numbering)", "col": 709, "pages": [362, 376], "kind": "sections", "cut": True},
        {"slug": "contra_eunomium_vii", "title": "Contra Eunomium, liber VII (Migne's numbering)", "col": 737, "pages": [376, 390], "kind": "sections", "cut": True},
        {"slug": "contra_eunomium_viii", "title": "Contra Eunomium, liber VIII (Migne's numbering)", "col": 765, "pages": [390, 407], "kind": "sections", "cut": True},
        {"slug": "contra_eunomium_ix", "title": "Contra Eunomium, liber IX (Migne's numbering)", "col": 799, "pages": [407, 420], "kind": "sections", "cut": True},
        {"slug": "contra_eunomium_x", "title": "Contra Eunomium, liber X (Migne's numbering)", "col": 825, "pages": [420, 434], "kind": "sections", "cut": True},
        {"slug": "contra_eunomium_xi", "title": "Contra Eunomium, liber XI (Migne's numbering)", "col": 853, "pages": [434, 449], "kind": "sections", "cut": True},
        {"slug": "contra_eunomium_xii", "title": "Contra Eunomium, liber XII (Migne's numbering)", "col": 883, "pages": [449, 462], "kind": "sections", "cut": True},
        {"slug": "contra_eunomium_xiib", "title": "Contra Eunomium, liber XIIb: In secundum Eunomii librum (Jaeger's book II)", "col": 909, "pages": [462, 568], "kind": "sections", "cut": True},
        {"slug": "antirrheticus_adversus_apolinarium", "title": "Antirrheticus adversus Apolinarium", "col": 1123, "pages": [569, 642], "kind": "sections", "cut": True},
        {"slug": "ad_theophilum_adversus_apollinaristas", "title": "Ad Theophilum, adversus Apollinaristas", "col": 1269, "pages": [642, 648], "kind": "sections", "cut": True},
        {"slug": "adversus_arium_et_sabellium", "title": "Adversus Arium et Sabellium (dubium)", "col": 1281, "pages": [648, 658], "kind": "sections", "cut": True},
        {"slug": "adversus_macedonianos", "title": "Adversus Macedonianos, de Spiritu sancto", "col": 1301, "pages": [658, 674], "kind": "sections", "cut": True},
    ],
    46: [
        # S. Gregorius Nyssenus III: ascetic and moral works, homilies, Lives, Letters.  Main scan: IA
        # patrologiae_cursus_completus_gr_vol_046, in order with no repeated pages.  Running heads: left
        # column = 2p - 15 (pp. 13-597).  Excluded pages: 1-12 (title pages, Monitum), 125 (notices on the Ad
        # Eustathium de Trinitate = PG 32 Basil ep. 189, and the Ad Tatianum de anima), 277 (notices on three
        # pieces printed in other volumes), 598-649 (Variorum notae, indexes).
        {"slug": "de_anima_et_resurrectione", "title": "De anima et resurrectione (Macrinia)", "col": 11, "pages": [13, 88], "kind": "sections"},
        {"slug": "de_infantibus_praemature_abreptis", "title": "De infantibus praemature abreptis", "col": 161, "pages": [88, 104], "kind": "sections", "cut": True},
        {"slug": "testimonia_adversus_judaeos", "title": "Testimonia adversus Judaeos (dubium)", "col": 193, "pages": [104, 124], "kind": "sections", "cut": True},
        {"slug": "ad_harmonium_de_professione_christiana", "title": "Ad Harmonium, quid nomen professiove Christianorum sibi velit", "col": 237, "pages": [126, 133], "kind": "sections"},
        {"slug": "de_perfectione", "title": "De perfectione, ad Olympium monachum", "col": 251, "pages": [133, 151], "kind": "sections", "cut": True},
        {"slug": "de_instituto_christiano", "title": "De instituto christiano", "col": 287, "pages": [151, 161], "kind": "sections", "cut": True},
        {"slug": "adversus_eos_qui_castigationes_aegre_ferunt", "title": "Adversus eos qui castigationes aegre ferunt", "col": 307, "pages": [161, 166], "kind": "sections", "cut": True},
        {"slug": "de_virginitate", "title": "De virginitate", "col": 317, "pages": [166, 215], "kind": "sections", "cut": True},
        {"slug": "adversus_eos_qui_differunt_baptismum", "title": "Adversus eos qui differunt baptismum", "col": 415, "pages": [215, 224], "kind": "sections", "cut": True},
        {"slug": "contra_usurarios", "title": "Contra usurarios", "col": 433, "pages": [224, 234], "kind": "sections", "cut": True},
        {"slug": "de_beneficentia", "title": "De beneficentia (De pauperibus amandis I)", "col": 453, "pages": [234, 243], "kind": "sections", "cut": True},
        {"slug": "in_illud_quatenus_uni_ex_his", "title": "In illud: Quatenus uni ex his fecistis (De pauperibus amandis II)", "col": 471, "pages": [243, 252], "kind": "sections", "cut": True},
        {"slug": "contra_fornicarios", "title": "Contra fornicarios", "col": 489, "pages": [252, 256], "kind": "sections", "cut": True},
        {"slug": "de_mortuis", "title": "De mortuis", "col": 497, "pages": [256, 276], "kind": "sections", "cut": True},
        {"slug": "contra_manichaeos_syllogismi", "title": "Contra Manichaeos syllogismi decem", "col": 541, "pages": [278, 279], "kind": "sections"},
        {"slug": "in_suam_ordinationem", "title": "In suam ordinationem", "col": 543, "pages": [279, 296], "kind": "sections", "cut": True},
        {"slug": "in_diem_luminum", "title": "In diem luminum (In baptismum Christi)", "col": 577, "pages": [296, 307], "kind": "sections", "cut": True},
        {"slug": "in_sanctum_pascha_orationes_v", "title": "In sanctum Pascha et de tridui spatio orationes V", "col": 599, "pages": [307, 352], "kind": "sections", "cut": True},
        {"slug": "in_ascensionem_christi", "title": "In ascensionem Christi", "col": 689, "pages": [352, 355], "kind": "sections", "cut": True},
        {"slug": "de_spiritu_sancto_in_pentecosten", "title": "De Spiritu sancto, sive in Pentecosten", "col": 695, "pages": [355, 358], "kind": "sections", "cut": True},
        {"slug": "in_sanctum_stephanum_i", "title": "In sanctum Stephanum I", "col": 701, "pages": [358, 368], "kind": "sections", "cut": True},
        {"slug": "in_sanctum_stephanum_ii", "title": "In sanctum Stephanum II", "col": 721, "pages": [368, 375], "kind": "sections", "cut": True},
        {"slug": "de_sancto_theodoro", "title": "De sancto Theodoro martyre", "col": 735, "pages": [375, 382], "kind": "sections", "cut": True},
        {"slug": "in_xl_martyres_i", "title": "In XL martyres I (Ia-Ib)", "col": 749, "pages": [382, 394], "kind": "sections", "cut": True},
        {"slug": "in_xl_martyres_ii", "title": "In XL martyres II", "col": 773, "pages": [394, 401], "kind": "sections", "cut": True},
        {"slug": "in_basilium_fratrem", "title": "In Basilium fratrem", "col": 787, "pages": [401, 417], "kind": "sections", "cut": True},
        {"slug": "de_vita_ephraem", "title": "De vita S. Ephraem Syri", "col": 819, "pages": [417, 433], "kind": "sections", "cut": True},
        {"slug": "in_meletium", "title": "Oratio funebris in Meletium episcopum", "col": 851, "pages": [433, 439], "kind": "sections", "cut": True},
        {"slug": "in_pulcheriam", "title": "Oratio consolatoria in Pulcheriam", "col": 863, "pages": [439, 446], "kind": "sections", "cut": True},
        {"slug": "in_flacillam", "title": "Oratio funebris in Flacillam imperatricem", "col": 877, "pages": [446, 454], "kind": "sections", "cut": True},
        {"slug": "de_vita_gregorii_thaumaturgi", "title": "De vita S. Gregorii Thaumaturgi", "col": 893, "pages": [454, 487], "kind": "sections", "cut": True},
        {"slug": "vita_macrinae", "title": "Vita S. Macrinae", "col": 959, "pages": [487, 507], "kind": "sections", "cut": True},
        {"slug": "epistolae", "title": "Epistolae", "col": 1000, "pages": [507, 570], "kind": "sections", "cut": True},
        {"slug": "in_diem_natalem_christi", "title": "In diem natalem Christi", "col": 1127, "pages": [571, 583], "kind": "sections"},
        {"slug": "in_occursum_domini", "title": "In occursum Domini (dubium)", "col": 1151, "pages": [583, 597], "kind": "sections", "cut": True},
    ],
    47: [
        # S. Joannes Chrysostomus I: prolegomena, Palladius' Dialogus, ascetic treatises.  Main scan: IA
        # patrologiae_cursus_completus_gr_vol_047.  Greek and Latin on separate pages under the same column
        # numbers; the Latin pages are excluded and dropped, so the Migne column is 2e + c over the Greek
        # pages (e = index among them), re-anchored after each Latin Monitum (pp. 277-279, 384-386).
        {"slug": "testimonia_de_vita", "title": "Prolegomena: Greek testimonies on Chrysostom's life (Martyrius of Antioch, Georgius etc.; Roman column numbers XLIII ff.)", "col": 43, "pages": [33, 55], "kind": "sections"},
        {"slug": "palladii_dialogus", "title": "Palladius, Dialogus de vita S. Joannis Chrysostomi", "col": 5, "pages": [61, 137], "kind": "sections"},
        {"slug": "ad_theodorum_lapsum_i", "title": "Ad Theodorum lapsum I", "col": 277, "pages": [237, 268], "kind": "sections"},
        {"slug": "ad_theodorum_lapsum_ii", "title": "Ad Theodorum lapsum II", "col": 309, "pages": [269, 276], "kind": "sections"},
        {"slug": "adversus_oppugnatores_i", "title": "Adversus oppugnatores vitae monasticae I", "col": 319, "pages": [280, 292], "kind": "sections"},
        {"slug": "adversus_oppugnatores_ii", "title": "Adversus oppugnatores vitae monasticae II: ad patrem infidelem", "col": 331, "pages": [292, 308], "kind": "sections", "cut": True},
        {"slug": "adversus_oppugnatores_iii", "title": "Adversus oppugnatores vitae monasticae III: ad patrem fidelem", "col": 349, "pages": [309, 352], "kind": "sections"},
        {"slug": "de_compunctione_i", "title": "De compunctione I, ad Demetrium", "col": 393, "pages": [355, 373], "kind": "sections"},
        {"slug": "de_compunctione_ii", "title": "De compunctione II, ad Stelechium", "col": 411, "pages": [374, 383], "kind": "sections"},
        {"slug": "ad_stagirium_i", "title": "Ad Stagirium a daemone vexatum I", "col": 425, "pages": [387, 410], "kind": "sections"},
        {"slug": "ad_stagirium_ii", "title": "Ad Stagirium a daemone vexatum II", "col": 447, "pages": [410, 434], "kind": "sections", "cut": True},
        {"slug": "ad_stagirium_iii", "title": "Ad Stagirium a daemone vexatum III", "col": 471, "pages": [434, 458], "kind": "sections", "cut": True},
        {"slug": "contra_eos_qui_subintroductas_habent", "title": "Contra eos qui subintroductas habent virgines", "col": 495, "pages": [458, 475], "kind": "sections", "cut": True},
        {"slug": "quod_regulares_feminae", "title": "Quod regulares feminae viris cohabitare non debeant", "col": 513, "pages": [475, 494], "kind": "sections", "cut": True},
    ],
    48: [
        # S. Joannes Chrysostomus II: De virginitate, De sacerdotio, Contra Anomoeos, Adversus Judaeos, De Lazaro; spuria.  Main scan IA patrologiae_cursus_completus_gr_vol_048;
        # Greek and Latin pages alternate under the same columns (Latin excluded and dropped); works
        # begin under titles in mid-page, so every work after the first is "cut".
        {"slug": "de_virginitate", "title": "De virginitate", "col": 533, "pages": [13, 80], "kind": "sections"},
        {"slug": "ad_viduam_juniorem", "title": "Ad viduam juniorem", "col": 599, "pages": [80, 89], "kind": "sections"},
        {"slug": "de_non_iterando_conjugio", "title": "De non iterando conjugio", "col": 609, "pages": [89, 103], "kind": "sections", "cut": True},
        {"slug": "de_sacerdotio_i", "title": "De sacerdotio I", "col": 623, "pages": [104, 112], "kind": "sections"},
        {"slug": "de_sacerdotio_ii", "title": "De sacerdotio II", "col": 631, "pages": [112, 120], "kind": "sections", "cut": True},
        {"slug": "de_sacerdotio_iii", "title": "De sacerdotio III", "col": 639, "pages": [120, 140], "kind": "sections", "cut": True},
        {"slug": "de_sacerdotio_iv", "title": "De sacerdotio IV", "col": 659, "pages": [140, 152], "kind": "sections", "cut": True},
        {"slug": "de_sacerdotio_v", "title": "De sacerdotio V", "col": 671, "pages": [152, 157], "kind": "sections", "cut": True},
        {"slug": "de_sacerdotio_vi", "title": "De sacerdotio VI", "col": 677, "pages": [157, 173], "kind": "sections", "cut": True},
        {"slug": "sermo_cum_presbyter_fuit_ordinatus", "title": "Sermo cum presbyter fuit ordinatus", "col": 693, "pages": [173, 181], "kind": "sections", "cut": True},
        {"slug": "contra_anomoeos_i", "title": "De incomprehensibili Dei natura (Contra Anomoeos I)", "col": 701, "pages": [181, 189], "kind": "sections", "cut": True},
        {"slug": "contra_anomoeos_ii", "title": "De incomprehensibili Dei natura (Contra Anomoeos II)", "col": 709, "pages": [189, 200], "kind": "sections", "cut": True},
        {"slug": "contra_anomoeos_iii", "title": "De incomprehensibili Dei natura (Contra Anomoeos III)", "col": 719, "pages": [200, 208], "kind": "sections", "cut": True},
        {"slug": "contra_anomoeos_iv", "title": "De incomprehensibili Dei natura (Contra Anomoeos IV)", "col": 727, "pages": [208, 216], "kind": "sections", "cut": True},
        {"slug": "contra_anomoeos_v", "title": "De incomprehensibili Dei natura (Contra Anomoeos V)", "col": 735, "pages": [216, 228], "kind": "sections", "cut": True},
        {"slug": "contra_anomoeos_vi", "title": "Contra Anomoeos VI: De beato Philogonio", "col": 747, "pages": [228, 236], "kind": "sections", "cut": True},
        {"slug": "contra_anomoeos_vii", "title": "Contra Anomoeos VII: De consubstantiali", "col": 755, "pages": [236, 248], "kind": "sections", "cut": True},
        {"slug": "contra_anomoeos_viii", "title": "Contra Anomoeos VIII: De petitione matris filiorum Zebedaei", "col": 767, "pages": [248, 260], "kind": "sections", "cut": True},
        {"slug": "contra_anomoeos_ix", "title": "Contra Anomoeos IX: In quatriduanum Lazarum", "col": 779, "pages": [260, 264], "kind": "sections", "cut": True},
        {"slug": "contra_anomoeos_x", "title": "Contra Anomoeos X: De Christi precibus", "col": 783, "pages": [264, 276], "kind": "sections", "cut": True},
        {"slug": "contra_anomoeos_xi", "title": "Contra Anomoeos XI", "col": 795, "pages": [276, 281], "kind": "sections", "cut": True},
        {"slug": "contra_anomoeos_xii", "title": "Contra Anomoeos XII: De Christi divinitate", "col": 801, "pages": [281, 293], "kind": "sections", "cut": True},
        {"slug": "contra_judaeos_et_gentiles", "title": "Contra Judaeos et gentiles quod Christus sit Deus", "col": 813, "pages": [293, 324], "kind": "sections", "cut": True},
        {"slug": "adversus_judaeos_i", "title": "Adversus Judaeos I", "col": 843, "pages": [324, 337], "kind": "sections", "cut": True},
        {"slug": "adversus_judaeos_ii", "title": "Adversus Judaeos II", "col": 857, "pages": [337, 341], "kind": "sections", "cut": True},
        {"slug": "adversus_judaeos_iii", "title": "Adversus Judaeos III", "col": 861, "pages": [341, 352], "kind": "sections", "cut": True},
        {"slug": "adversus_judaeos_iv", "title": "Adversus Judaeos IV", "col": 871, "pages": [352, 364], "kind": "sections", "cut": True},
        {"slug": "adversus_judaeos_v", "title": "Adversus Judaeos V", "col": 883, "pages": [364, 384], "kind": "sections", "cut": True},
        {"slug": "adversus_judaeos_vi", "title": "Adversus Judaeos VI", "col": 903, "pages": [384, 396], "kind": "sections", "cut": True},
        {"slug": "adversus_judaeos_vii", "title": "Adversus Judaeos VII", "col": 915, "pages": [396, 408], "kind": "sections", "cut": True},
        {"slug": "adversus_judaeos_viii", "title": "Adversus Judaeos VIII", "col": 927, "pages": [408, 425], "kind": "sections", "cut": True},
        {"slug": "de_anathemate", "title": "De anathemate", "col": 945, "pages": [425, 433], "kind": "sections", "cut": True},
        {"slug": "in_kalendas", "title": "In Kalendas", "col": 953, "pages": [433, 444], "kind": "sections", "cut": True},
        {"slug": "de_lazaro_i", "title": "De Lazaro I", "col": 963, "pages": [444, 461], "kind": "sections", "cut": True},
        {"slug": "de_lazaro_ii", "title": "De Lazaro II", "col": 981, "pages": [461, 472], "kind": "sections", "cut": True},
        {"slug": "de_lazaro_iii", "title": "De Lazaro III", "col": 991, "pages": [472, 485], "kind": "sections", "cut": True},
        {"slug": "de_lazaro_iv", "title": "De Lazaro IV", "col": 1005, "pages": [485, 497], "kind": "sections", "cut": True},
        {"slug": "de_lazaro_v", "title": "De Lazaro V", "col": 1017, "pages": [497, 508], "kind": "sections", "cut": True},
        {"slug": "de_lazaro_vi", "title": "De Lazaro VI", "col": 1027, "pages": [508, 524], "kind": "sections", "cut": True},
        {"slug": "de_lazaro_vii", "title": "De Lazaro VII", "col": 1043, "pages": [524, 536], "kind": "sections", "cut": True},
        {"slug": "spuria_quod_non_oportet_ridere", "title": "Spuria: Quod non oportet ridere et jocari (ascetam)", "col": 1055, "pages": [536, 540], "kind": "sections", "cut": True},
        {"slug": "spuria_de_jejunio_et_eleemosyna", "title": "Spuria: De jejunio et eleemosyna", "col": 1059, "pages": [540, 544], "kind": "sections", "cut": True},
        {"slug": "spuria_theodori_lapsi_epistola", "title": "Dubia: Theodori lapsi epistola ad Chrysostomum", "col": 1063, "pages": [544, 548], "kind": "sections", "cut": True},
        {"slug": "spuria_de_sacerdotio_vii", "title": "Spuria: De sacerdotio VII", "col": 1067, "pages": [548, 552], "kind": "sections", "cut": True},
        {"slug": "spuria_christi_discipulum_benignum", "title": "Spuria: Christi discipulum benignum esse debere", "col": 1071, "pages": [552, 553], "kind": "sections", "cut": True},
        {"slug": "spuria_simulata_figura_fugienda", "title": "Spuria: Hoti epiplaston schema... (simulata figura fugienda)", "col": 1073, "pages": [553, 556], "kind": "sections", "cut": True},
        {"slug": "spuria_contra_judaeos_gentiles_haereticos", "title": "Spuria: Contra Judaeos, gentiles et haereticos", "col": 1075, "pages": [556, 561], "kind": "sections", "cut": True},
        {"slug": "spuria_de_fide_et_lege_naturae", "title": "Spuria: De fide et lege naturae", "col": 1081, "pages": [561, 568], "kind": "sections", "cut": True},
        {"slug": "spuria_de_sancta_trinitate", "title": "Spuria: De sancta et consubstantiali Trinitate", "col": 1087, "pages": [568, 576], "kind": "sections", "cut": True},
    ],
    49: [
        # S. Joannes Chrysostomus III/1: Ad populum Antiochenum, Catecheses, De diabolo, De poenitentia, festal homilies.  Main scan IA patrologiae_cursus_completus_gr_vol_049;
        # Greek and Latin pages alternate under the same columns (Latin excluded and dropped); works
        # begin under titles in mid-page, so every work after the first is "cut".
        {"slug": "ad_populum_antiochenum", "title": "Ad populum Antiochenum homiliae XXI (De statuis)", "col": 15, "pages": [16, 224], "kind": "sections"},
        {"slug": "catechesis_ad_illuminandos_i", "title": "Catechesis ad illuminandos I", "col": 223, "pages": [224, 232], "kind": "sections", "cut": True},
        {"slug": "catechesis_ad_illuminandos_ii", "title": "Catechesis ad illuminandos II", "col": 231, "pages": [232, 241], "kind": "sections", "cut": True},
        {"slug": "de_diabolo_tentatore", "title": "De diabolo tentatore homiliae III", "col": 241, "pages": [241, 273], "kind": "sections", "cut": True},
        {"slug": "de_poenitentia", "title": "De poenitentia homiliae IX", "col": 277, "pages": [273, 345], "kind": "sections", "cut": True},
        {"slug": "in_diem_natalem", "title": "In diem natalem D. N. Jesu Christi", "col": 351, "pages": [345, 357], "kind": "sections", "cut": True},
        {"slug": "de_baptismo_christi", "title": "De baptismo Christi", "col": 363, "pages": [357, 368], "kind": "sections", "cut": True},
        {"slug": "de_proditione_judae_i", "title": "De proditione Judae I", "col": 373, "pages": [368, 376], "kind": "sections", "cut": True},
        {"slug": "de_proditione_judae_ii", "title": "De proditione Judae II", "col": 381, "pages": [376, 388], "kind": "sections", "cut": True},
        {"slug": "de_coemeterio_et_de_cruce", "title": "De coemeterio et de cruce", "col": 393, "pages": [388, 393], "kind": "sections", "cut": True},
        {"slug": "de_cruce_et_latrone_i", "title": "De cruce et latrone I", "col": 399, "pages": [393, 401], "kind": "sections", "cut": True},
        {"slug": "de_cruce_et_latrone_ii", "title": "De cruce et latrone II", "col": 407, "pages": [401, 409], "kind": "sections", "cut": True},
    ],
    50: [
        # S. Joannes Chrysostomus III/2: festal and panegyric homilies (martyrs, S. Paul, Babylas); spuria.  Main scan IA patrologiae_cursus_completus_gr_vol_050;
        # Greek and Latin pages alternate under the same columns (Latin excluded and dropped); works
        # begin under titles in mid-page, so every work after the first is "cut".
        {"slug": "de_resurrectione_mortuorum", "title": "De resurrectione mortuorum", "col": 417, "pages": [14, 30], "kind": "sections"},
        {"slug": "contra_ebriosos", "title": "Contra ebriosos et de resurrectione", "col": 433, "pages": [30, 38], "kind": "sections", "cut": True},
        {"slug": "in_ascensionem", "title": "In ascensionem D. N. Jesu Christi", "col": 441, "pages": [38, 50], "kind": "sections", "cut": True},
        {"slug": "de_sancta_pentecoste_i", "title": "De sancta Pentecoste I", "col": 453, "pages": [50, 61], "kind": "sections", "cut": True},
        {"slug": "de_sancta_pentecoste_ii", "title": "De sancta Pentecoste II", "col": 463, "pages": [61, 69], "kind": "sections", "cut": True},
        {"slug": "de_laudibus_pauli_i", "title": "De laudibus S. Pauli I", "col": 473, "pages": [70, 74], "kind": "sections"},
        {"slug": "de_laudibus_pauli_ii", "title": "De laudibus S. Pauli II", "col": 477, "pages": [74, 81], "kind": "sections", "cut": True},
        {"slug": "de_laudibus_pauli_iii", "title": "De laudibus S. Pauli III", "col": 483, "pages": [81, 85], "kind": "sections", "cut": True},
        {"slug": "de_laudibus_pauli_iv", "title": "De laudibus S. Pauli IV", "col": 487, "pages": [85, 93], "kind": "sections", "cut": True},
        {"slug": "de_laudibus_pauli_v", "title": "De laudibus S. Pauli V", "col": 495, "pages": [93, 98], "kind": "sections", "cut": True},
        {"slug": "de_laudibus_pauli_vi", "title": "De laudibus S. Pauli VI", "col": 501, "pages": [98, 105], "kind": "sections", "cut": True},
        {"slug": "de_laudibus_pauli_vii", "title": "De laudibus S. Pauli VII", "col": 507, "pages": [105, 113], "kind": "sections", "cut": True},
        {"slug": "de_s_meletio", "title": "De S. Meletio Antiocheno", "col": 515, "pages": [113, 117], "kind": "sections", "cut": True},
        {"slug": "in_s_lucianum", "title": "In S. Lucianum martyrem", "col": 519, "pages": [117, 126], "kind": "sections", "cut": True},
        {"slug": "in_s_babylam", "title": "In S. Babylam", "col": 527, "pages": [126, 130], "kind": "sections", "cut": True},
        {"slug": "de_s_babyla_contra_julianum", "title": "De S. Babyla contra Julianum et gentiles", "col": 533, "pages": [130, 169], "kind": "sections", "cut": True},
        {"slug": "in_juventinum_et_maximinum", "title": "In SS. Juventinum et Maximinum", "col": 571, "pages": [169, 177], "kind": "sections", "cut": True},
        {"slug": "de_s_pelagia", "title": "De S. Pelagia virgine et martyre", "col": 579, "pages": [177, 185], "kind": "sections", "cut": True},
        {"slug": "in_s_ignatium", "title": "In S. Ignatium martyrem", "col": 587, "pages": [185, 194], "kind": "sections", "cut": True},
        {"slug": "in_s_eustathium", "title": "In S. Eustathium Antiochenum", "col": 597, "pages": [194, 202], "kind": "sections", "cut": True},
        {"slug": "in_s_romanum_i", "title": "In S. Romanum martyrem I", "col": 605, "pages": [202, 209], "kind": "sections", "cut": True},
        {"slug": "in_s_romanum_ii", "title": "In S. Romanum martyrem II", "col": 611, "pages": [209, 214], "kind": "sections", "cut": True},
        {"slug": "in_maccabaeos_i", "title": "In sanctos Maccabaeos I", "col": 617, "pages": [214, 221], "kind": "sections", "cut": True},
        {"slug": "in_maccabaeos_ii", "title": "In sanctos Maccabaeos II", "col": 623, "pages": [221, 222], "kind": "sections", "cut": True},
        {"slug": "in_maccabaeos_iii", "title": "In sanctos Maccabaeos III", "col": 625, "pages": [225, 226], "kind": "sections"},
        {"slug": "de_ss_bernice_et_prosdoce", "title": "De SS. Bernice et Prosdoce virginibus et Domnina", "col": 629, "pages": [226, 238], "kind": "sections", "cut": True},
        {"slug": "in_quatriduanum_lazarum", "title": "In quatriduanum Lazarum; De sanctis martyribus (not separated)", "col": 641, "pages": [238, 250], "kind": "sections", "cut": True},
        {"slug": "non_esse_ad_gratiam_concionandum", "title": "Non esse ad gratiam concionandum", "col": 653, "pages": [250, 258], "kind": "sections", "cut": True},
        {"slug": "in_martyres", "title": "Homilia in martyres", "col": 661, "pages": [261, 262], "kind": "sections"},
        {"slug": "in_s_julianum", "title": "In S. Julianum martyrem", "col": 665, "pages": [262, 273], "kind": "sections", "cut": True},
        {"slug": "in_s_barlaam", "title": "In S. Barlaam martyrem", "col": 675, "pages": [273, 281], "kind": "sections", "cut": True},
        {"slug": "de_s_droside", "title": "De S. Droside martyre", "col": 683, "pages": [281, 290], "kind": "sections", "cut": True},
        {"slug": "in_martyres_aegyptios", "title": "In martyres Aegyptios", "col": 693, "pages": [290, 297], "kind": "sections", "cut": True},
        {"slug": "de_s_phoca", "title": "De S. hieromartyre Phoca", "col": 699, "pages": [297, 302], "kind": "sections", "cut": True},
        {"slug": "in_omnes_sanctos", "title": "Encomium in omnes sanctos", "col": 705, "pages": [302, 309], "kind": "sections", "cut": True},
        {"slug": "de_terrae_motu", "title": "De terrae motu", "col": 713, "pages": [310, 313], "kind": "sections"},
        {"slug": "de_proditione_judae", "title": "Spuria: In proditionem Judae", "col": 715, "pages": [313, 317], "kind": "sections", "cut": True},
        {"slug": "de_s_basso", "title": "De S. Basso martyre", "col": 719, "pages": [317, 322], "kind": "sections", "cut": True},
        {"slug": "in_petrum_et_eliam", "title": "In Petrum apostolum et Eliam prophetam", "col": 725, "pages": [322, 333], "kind": "sections", "cut": True},
        {"slug": "spuria_in_abraham", "title": "Spuria: In beatum Abraham", "col": 737, "pages": [334, 342], "kind": "sections"},
        {"slug": "spuria_in_theclam", "title": "Spuria: In S. protomartyrem Theclam", "col": 745, "pages": [342, 346], "kind": "sections", "cut": True},
        {"slug": "spuria_de_fato_i", "title": "Spuria: De fato et providentia I", "col": 749, "pages": [346, 354], "kind": "sections", "cut": True},
        {"slug": "spuria_de_fato_ii", "title": "Spuria: De fato et providentia II", "col": 757, "pages": [354, 357], "kind": "sections", "cut": True},
        {"slug": "spuria_de_fato_iii", "title": "Spuria: De fato et providentia III", "col": 759, "pages": [357, 362], "kind": "sections", "cut": True},
        {"slug": "spuria_de_fato_iv", "title": "Spuria: De fato et providentia IV", "col": 765, "pages": [362, 366], "kind": "sections", "cut": True},
        {"slug": "spuria_de_fato_v_vi", "title": "Spuria: De fato et providentia V-VI", "col": 769, "pages": [366, 372], "kind": "sections", "cut": True},
        {"slug": "spuria_de_precatione_i", "title": "Spuria: De precatione I", "col": 775, "pages": [373, 377], "kind": "sections"},
        {"slug": "spuria_de_precatione_ii", "title": "Spuria: De precatione II", "col": 779, "pages": [377, 385], "kind": "sections", "cut": True},
        {"slug": "spuria_in_conceptionem_joannis", "title": "Spuria: In conceptionem S. Joannis Baptistae", "col": 787, "pages": [385, 389], "kind": "sections", "cut": True},
        {"slug": "spuria_in_annuntiationem", "title": "Spuria: In Annuntiationem B. V. Mariae", "col": 791, "pages": [389, 393], "kind": "sections", "cut": True},
        {"slug": "spuria_homilia_mellontos", "title": "Spuria: Homilia (inc. Mellontos, agapetoi, tou koinou Soteros)", "col": 795, "pages": [393, 398], "kind": "sections", "cut": True},
        {"slug": "spuria_in_joannem_prodromum", "title": "Spuria: In S. Joannem Prodromum", "col": 801, "pages": [398, 402], "kind": "sections", "cut": True},
        {"slug": "spuria_in_theophania", "title": "Spuria: In sancta Theophania", "col": 805, "pages": [402, 413], "kind": "sections", "cut": True},
        {"slug": "spuria_in_venerabilem_crucem", "title": "Spuria: In venerabilem crucem", "col": 815, "pages": [414, 418], "kind": "sections"},
        {"slug": "spuria_in_triduanam_resurrectionem", "title": "Spuria: In triduanam resurrectionem Domini", "col": 821, "pages": [418, 421], "kind": "sections", "cut": True},
    ],
    51: [
        # S. Joannes Chrysostomus III/3: homilies on passages of Scripture (De mutatione nominum, In principium
        # Actorum, Habentes eundem spiritum...).  Main scan IA patrologiae_cursus_completus_gr_vol_051; Greek and
        # Latin pages alternate (Latin excluded and dropped); p233 (a damaged copy of p235: its left column is
        # misplaced) and p264 (a second copy of p262) are dropped.  Column = 2e + 17 over the Greek pages.
        {"slug": "de_decem_millium_talentorum_debitore", "title": "De decem millium talentorum debitore", "col": 17, "pages": [16, 31], "kind": "sections"},
        {"slug": "in_illud_pater_si_possibile_est", "title": "In illud: Pater, si possibile est, transeat", "col": 33, "pages": [34, 42], "kind": "sections"},
        {"slug": "de_angusta_porta_et_oratione_dominica", "title": "In illud: Angusta est porta; et de oratione dominica", "col": 43, "pages": [43, 50], "kind": "sections"},
        {"slug": "in_paralyticum_demissum_per_tectum", "title": "In paralyticum demissum per tectum", "col": 49, "pages": [50, 66], "kind": "sections", "cut": True},
        {"slug": "in_principium_actorum_i", "title": "In inscriptionem altaris et in principium Actorum I", "col": 67, "pages": [68, 76], "kind": "sections"},
        {"slug": "in_principium_actorum_ii", "title": "In principium Actorum II", "col": 77, "pages": [77, 88], "kind": "sections"},
        {"slug": "in_principium_actorum_iii", "title": "In principium Actorum III: De utilitate lectionis Scripturarum", "col": 87, "pages": [88, 97], "kind": "sections", "cut": True},
        {"slug": "in_principium_actorum_iv", "title": "In principium Actorum IV: Cur in Pentecoste Acta legantur", "col": 97, "pages": [97, 113], "kind": "sections", "cut": True},
        {"slug": "de_mutatione_nominum_i", "title": "De mutatione nominum I", "col": 113, "pages": [113, 124], "kind": "sections", "cut": True},
        {"slug": "de_mutatione_nominum_ii", "title": "De mutatione nominum II", "col": 123, "pages": [124, 132], "kind": "sections", "cut": True},
        {"slug": "de_mutatione_nominum_iii", "title": "De mutatione nominum III", "col": 131, "pages": [132, 144], "kind": "sections", "cut": True},
        {"slug": "de_mutatione_nominum_iv", "title": "De mutatione nominum IV", "col": 143, "pages": [144, 156], "kind": "sections", "cut": True},
        {"slug": "de_gloria_in_tribulationibus", "title": "De gloria in tribulationibus", "col": 155, "pages": [156, 165], "kind": "sections", "cut": True},
        {"slug": "in_illud_scimus_quoniam_diligentibus_deum", "title": "In illud: Scimus quoniam diligentibus Deum omnia cooperantur in bonum", "col": 165, "pages": [165, 172], "kind": "sections", "cut": True},
        {"slug": "in_illud_si_esurierit_inimicus", "title": "In illud: Si esurierit inimicus tuus", "col": 171, "pages": [172, 188], "kind": "sections", "cut": True},
        {"slug": "in_illud_salutate_priscillam_i", "title": "In illud: Salutate Priscillam et Aquilam I", "col": 187, "pages": [188, 196], "kind": "sections", "cut": True},
        {"slug": "in_illud_salutate_priscillam_ii", "title": "In illud: Salutate Priscillam et Aquilam II", "col": 195, "pages": [196, 208], "kind": "sections", "cut": True},
        {"slug": "in_illud_propter_fornicationes", "title": "In illud: Propter fornicationes uxorem quisque suam habeat", "col": 207, "pages": [208, 217], "kind": "sections", "cut": True},
        {"slug": "de_libello_repudii", "title": "De libello repudii", "col": 217, "pages": [217, 224], "kind": "sections", "cut": True},
        {"slug": "quales_ducendae_sint_uxores", "title": "Quales ducendae sint uxores", "col": 225, "pages": [225, 243], "kind": "sections"},
        {"slug": "in_illud_nolo_vos_ignorare", "title": "In illud: Nolo vos ignorare, fratres", "col": 241, "pages": [243, 254], "kind": "sections", "cut": True},
        {"slug": "in_dictum_pauli_oportet_haereses_esse", "title": "In dictum Pauli: Oportet haereses esse", "col": 253, "pages": [255, 262], "kind": "sections"},
        {"slug": "de_eleemosyna", "title": "De eleemosyna", "col": 261, "pages": [265, 276], "kind": "sections"},
        {"slug": "in_illud_habentes_eundem_spiritum_i", "title": "In illud: Habentes eundem spiritum I", "col": 271, "pages": [276, 285], "kind": "sections", "cut": True},
        {"slug": "in_illud_habentes_eundem_spiritum_ii", "title": "In illud: Habentes eundem spiritum II", "col": 281, "pages": [285, 293], "kind": "sections", "cut": True},
        {"slug": "in_illud_habentes_eundem_spiritum_iii", "title": "In illud: Habentes eundem spiritum III", "col": 289, "pages": [293, 305], "kind": "sections", "cut": True},
        {"slug": "in_illud_utinam_sustineretis_modicum", "title": "In illud: Utinam sustineretis modicum", "col": 301, "pages": [305, 316], "kind": "sections", "cut": True},
        {"slug": "de_profectu_evangelii", "title": "De profectu Evangelii (In illud: Sive per occasionem sive per veritatem)", "col": 311, "pages": [316, 325], "kind": "sections", "cut": True},
        {"slug": "in_illud_vidua_eligatur", "title": "In illud: Vidua eligatur", "col": 321, "pages": [325, 341], "kind": "sections", "cut": True},
        {"slug": "in_eliam_et_viduam", "title": "In Eliam et viduam", "col": 337, "pages": [341, 352], "kind": "sections", "cut": True},
        {"slug": "de_futurae_vitae_deliciis", "title": "De futurae vitae deliciis", "col": 347, "pages": [352, 357], "kind": "sections", "cut": True},
        {"slug": "de_non_publicandis_fratrum_peccatis", "title": "De non publicandis fratrum peccatis", "col": 353, "pages": [357, 368], "kind": "sections", "cut": True},
        {"slug": "non_esse_desperandum", "title": "Non esse desperandum", "col": 365, "pages": [369, 376], "kind": "sections"},
        {"slug": "in_illud_in_faciem_ei_restiti", "title": "In illud: In faciem ei restiti", "col": 371, "pages": [376, 392], "kind": "sections", "cut": True},
    ],
    52: [
        # S. Joannes Chrysostomus III/4: homilies on Eutropius and the exile, Quod nemo laeditur, Ad eos qui
        # scandalizati sunt, letters (Innocent, Olympias, others), spuria.  Main scan IA
        # patrologiae_cursus_completus_gr_vol_052; Latin pages excluded and dropped.  Column = 2e + c over the
        # Greek pages, re-anchored after irregular Latin groups (monita): see SCAN_FIXES.
        {"slug": "in_eutropium", "title": "Homilia in Eutropium eunuchum", "col": 391, "pages": [17, 21], "kind": "sections"},
        {"slug": "de_capto_eutropio", "title": "De capto Eutropio et de divitiarum vanitate", "col": 395, "pages": [21, 38], "kind": "sections", "cut": True},
        {"slug": "cum_saturninus_et_aurelianus", "title": "Homilia cum Saturninus et Aurelianus acti essent in exsilium", "col": 413, "pages": [38, 51], "kind": "sections", "cut": True},
        {"slug": "sermo_antequam_iret_in_exsilium", "title": "Sermo antequam iret in exsilium", "col": 427, "pages": [51, 59], "kind": "sections", "cut": True},
        {"slug": "sermo_cum_iret_in_exsilium", "title": "Sermo cum iret in exsilium", "col": 435, "pages": [59, 65], "kind": "sections", "cut": True},
        {"slug": "post_reditum_a_priore_exsilio", "title": "Post reditum a priore exsilio (I-II)", "col": 439, "pages": [65, 69], "kind": "sections", "cut": True},
        {"slug": "de_muliere_chananaea", "title": "Homilia de muliere Chananaea", "col": 449, "pages": [70, 81], "kind": "sections"},
        {"slug": "quod_nemo_laeditur", "title": "Quod nemo laeditur nisi a seipso", "col": 459, "pages": [81, 101], "kind": "sections", "cut": True},
        {"slug": "ad_eos_qui_scandalizati_sunt", "title": "Ad eos qui scandalizati sunt ob adversitates", "col": 479, "pages": [101, 150], "kind": "sections", "cut": True},
        {"slug": "epistolae_ad_innocentium", "title": "Epistolae ad Innocentium papam, with Innocent's letters", "col": 529, "pages": [150, 162], "kind": "sections", "cut": True},
        {"slug": "epistolae", "title": "Epistolae: ad Olympiadem XVII, ad diversos CCXLII (with the letter of Constantius presbyter)", "col": 549, "pages": [168, 364], "kind": "sections"},
        {"slug": "ad_caesarium_monachum", "title": "Epistola ad Caesarium monachum (Greek fragments)", "col": 757, "pages": [374, 378], "kind": "sections"},
        {"slug": "laus_diodori_episcopi", "title": "Laus Diodori episcopi", "col": 761, "pages": [378, 382], "kind": "sections", "cut": True},
        {"slug": "in_sanctum_pascha", "title": "Spuria: In sanctum Pascha", "col": 765, "pages": [382, 390], "kind": "sections", "cut": True},
        {"slug": "spuria_in_ascensionem_i", "title": "Spuria: In ascensionem D. N. Jesu Christi", "col": 773, "pages": [390, 409], "kind": "sections", "cut": True},
        {"slug": "spuria_in_ascensionem_ii", "title": "Spuria: In ascensionem, homilia I", "col": 791, "pages": [409, 410], "kind": "sections", "cut": True},
        {"slug": "spuria_in_ascensionem_iii", "title": "Spuria: In ascensionem", "col": 793, "pages": [410, 417], "kind": "sections", "cut": True},
        {"slug": "spuria_in_ascensionem_iv", "title": "Spuria: In ascensionem, sermo", "col": 799, "pages": [417, 421], "kind": "sections", "cut": True},
        {"slug": "spuria_in_pentecosten_i", "title": "Spuria: In Pentecosten, sermo I", "col": 803, "pages": [421, 425], "kind": "sections", "cut": True},
        {"slug": "spuria_in_pentecosten_ii", "title": "Spuria: In sanctam Pentecosten, sermo II", "col": 807, "pages": [425, 430], "kind": "sections", "cut": True},
        {"slug": "spuria_de_spiritu_sancto", "title": "Spuria: Homilia de Spiritu sancto", "col": 813, "pages": [430, 445], "kind": "sections", "cut": True},
        {"slug": "spuria_in_memoriam_martyrum", "title": "Spuria: In memoriam martyrum", "col": 827, "pages": [445, 453], "kind": "sections", "cut": True},
        {"slug": "spuria_in_adorationem_crucis", "title": "Spuria: In adorationem venerandae crucis", "col": 835, "pages": [453, 457], "kind": "sections", "cut": True},
        {"slug": "spuria_de_cruce_non_erubescendo", "title": "Spuria: Non erubescendum esse de cruce", "col": 841, "pages": [458, 461], "kind": "sections"},
    ],
    53: [
        # S. Joannes Chrysostomus IV/1: Homiliae in Genesim I-XLI.  Main scan IA patrologiae_cursus_completus_gr_vol_053;
        # Latin pages excluded and dropped; column = 2e + 21 over the Greek pages, no irregularities.
        {"slug": "hom_in_genesim_01", "title": "Homiliae in Genesim I", "col": 21, "pages": [23, 27], "kind": "sections"},
        {"slug": "hom_in_genesim_02", "title": "Homiliae in Genesim II", "col": 25, "pages": [27, 34], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_03", "title": "Homiliae in Genesim III", "col": 31, "pages": [34, 42], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_04", "title": "Homiliae in Genesim IV", "col": 39, "pages": [42, 50], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_05", "title": "Homiliae in Genesim V", "col": 47, "pages": [50, 55], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_06", "title": "Homiliae in Genesim VI", "col": 53, "pages": [55, 63], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_07", "title": "Homiliae in Genesim VII", "col": 61, "pages": [63, 71], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_08", "title": "Homiliae in Genesim VIII", "col": 69, "pages": [71, 78], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_09", "title": "Homiliae in Genesim IX", "col": 75, "pages": [78, 83], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_10", "title": "Homiliae in Genesim X", "col": 81, "pages": [83, 91], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_11", "title": "Homiliae in Genesim XI", "col": 89, "pages": [91, 99], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_12", "title": "Homiliae in Genesim XII", "col": 97, "pages": [99, 106], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_13", "title": "Homiliae in Genesim XIII", "col": 105, "pages": [107, 111], "kind": "sections"},
        {"slug": "hom_in_genesim_14", "title": "Homiliae in Genesim XIV", "col": 111, "pages": [114, 119], "kind": "sections"},
        {"slug": "hom_in_genesim_15", "title": "Homiliae in Genesim XV", "col": 117, "pages": [119, 127], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_16", "title": "Homiliae in Genesim XVI", "col": 125, "pages": [127, 135], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_17", "title": "Homiliae in Genesim XVII", "col": 133, "pages": [135, 150], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_18", "title": "Homiliae in Genesim XVIII", "col": 147, "pages": [150, 159], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_19", "title": "Homiliae in Genesim XIX", "col": 157, "pages": [159, 167], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_20", "title": "Homiliae in Genesim XX", "col": 165, "pages": [167, 175], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_21", "title": "Homiliae in Genesim XXI", "col": 175, "pages": [178, 187], "kind": "sections"},
        {"slug": "hom_in_genesim_22", "title": "Homiliae in Genesim XXII", "col": 185, "pages": [187, 198], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_23", "title": "Homiliae in Genesim XXIII", "col": 195, "pages": [198, 207], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_24", "title": "Homiliae in Genesim XXIV", "col": 205, "pages": [207, 219], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_25", "title": "Homiliae in Genesim XXV", "col": 217, "pages": [219, 231], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_26", "title": "Homiliae in Genesim XXVI", "col": 229, "pages": [231, 242], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_27", "title": "Homiliae in Genesim XXVII", "col": 239, "pages": [242, 254], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_28", "title": "Homiliae in Genesim XXVIII", "col": 251, "pages": [254, 262], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_29", "title": "Homiliae in Genesim XXIX", "col": 259, "pages": [262, 275], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_30", "title": "Homiliae in Genesim XXX", "col": 273, "pages": [275, 283], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_31", "title": "Homiliae in Genesim XXXI", "col": 281, "pages": [283, 294], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_32", "title": "Homiliae in Genesim XXXII", "col": 291, "pages": [294, 307], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_33", "title": "Homiliae in Genesim XXXIII", "col": 305, "pages": [307, 314], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_34", "title": "Homiliae in Genesim XXXIV", "col": 311, "pages": [314, 323], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_35", "title": "Homiliae in Genesim XXXV", "col": 321, "pages": [323, 334], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_36", "title": "Homiliae in Genesim XXXVI", "col": 331, "pages": [334, 343], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_37", "title": "Homiliae in Genesim XXXVII", "col": 341, "pages": [343, 351], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_38", "title": "Homiliae in Genesim XXXVIII", "col": 349, "pages": [351, 362], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_39", "title": "Homiliae in Genesim XXXIX", "col": 359, "pages": [362, 370], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_40", "title": "Homiliae in Genesim XL", "col": 367, "pages": [370, 375], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_41", "title": "Homiliae in Genesim XLI", "col": 373, "pages": [375, 386], "kind": "sections", "cut": True},
    ],
    54: [
        # S. Joannes Chrysostomus IV/2: Homiliae in Genesim XLII-LXVII, Sermones in Genesim IX, De Anna V, De Davide et
        # Saule III.  Main scan IA patrologiae_cursus_completus_gr_vol_054; column = 2e + 385 over the Greek pages.
        {"slug": "hom_in_genesim_42", "title": "Homiliae in Genesim XLII", "col": 385, "pages": [11, 22], "kind": "sections"},
        {"slug": "hom_in_genesim_43", "title": "Homiliae in Genesim XLIII", "col": 395, "pages": [22, 31], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_44", "title": "Homiliae in Genesim XLIV", "col": 405, "pages": [31, 39], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_45", "title": "Homiliae in Genesim XLV", "col": 413, "pages": [39, 47], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_46", "title": "Homiliae in Genesim XLVI", "col": 421, "pages": [47, 54], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_47", "title": "Homiliae in Genesim XLVII", "col": 427, "pages": [54, 59], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_48", "title": "Homiliae in Genesim XLVIII", "col": 433, "pages": [59, 70], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_49", "title": "Homiliae in Genesim XLIX", "col": 443, "pages": [70, 74], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_50", "title": "Homiliae in Genesim L", "col": 447, "pages": [74, 78], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_51", "title": "Homiliae in Genesim LI", "col": 451, "pages": [78, 82], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_52", "title": "Homiliae in Genesim LII", "col": 455, "pages": [82, 90], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_53", "title": "Homiliae in Genesim LIII", "col": 463, "pages": [90, 98], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_54", "title": "Homiliae in Genesim LIV", "col": 471, "pages": [98, 106], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_55", "title": "Homiliae in Genesim LV", "col": 479, "pages": [106, 111], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_56", "title": "Homiliae in Genesim LVI", "col": 485, "pages": [111, 119], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_57", "title": "Homiliae in Genesim LVII", "col": 493, "pages": [119, 131], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_58", "title": "Homiliae in Genesim LVIII", "col": 505, "pages": [131, 139], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_59", "title": "Homiliae in Genesim LIX", "col": 513, "pages": [139, 146], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_60", "title": "Homiliae in Genesim LX", "col": 519, "pages": [146, 151], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_61", "title": "Homiliae in Genesim LXI", "col": 525, "pages": [151, 158], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_62", "title": "Homiliae in Genesim LXII", "col": 531, "pages": [158, 166], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_63", "title": "Homiliae in Genesim LXIII", "col": 539, "pages": [166, 174], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_64", "title": "Homiliae in Genesim LXIV", "col": 547, "pages": [174, 183], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_65", "title": "Homiliae in Genesim LXV", "col": 557, "pages": [183, 191], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_66", "title": "Homiliae in Genesim LXVI", "col": 565, "pages": [191, 198], "kind": "sections", "cut": True},
        {"slug": "hom_in_genesim_67", "title": "Homiliae in Genesim LXVII", "col": 571, "pages": [198, 206], "kind": "sections", "cut": True},
        {"slug": "sermo_in_genesim_1", "title": "Sermones in Genesim I", "col": 581, "pages": [207, 211], "kind": "sections"},
        {"slug": "sermo_in_genesim_2", "title": "Sermones in Genesim II", "col": 585, "pages": [211, 215], "kind": "sections", "cut": True},
        {"slug": "sermo_in_genesim_3", "title": "Sermones in Genesim III", "col": 589, "pages": [215, 219], "kind": "sections", "cut": True},
        {"slug": "sermo_in_genesim_4", "title": "Sermones in Genesim IV", "col": 593, "pages": [219, 223], "kind": "sections", "cut": True},
        {"slug": "sermo_in_genesim_5", "title": "Sermones in Genesim V", "col": 599, "pages": [226, 230], "kind": "sections"},
        {"slug": "sermo_in_genesim_6", "title": "Sermones in Genesim VI", "col": 603, "pages": [230, 234], "kind": "sections", "cut": True},
        {"slug": "sermo_in_genesim_7", "title": "Sermones in Genesim VII", "col": 607, "pages": [234, 242], "kind": "sections", "cut": True},
        {"slug": "sermo_in_genesim_8", "title": "Sermones in Genesim VIII", "col": 615, "pages": [242, 246], "kind": "sections", "cut": True},
        {"slug": "sermo_in_genesim_9", "title": "Sermones in Genesim IX", "col": 619, "pages": [246, 258], "kind": "sections", "cut": True},
        {"slug": "de_anna_1", "title": "De Anna sermones I", "col": 631, "pages": [258, 270], "kind": "sections", "cut": True},
        {"slug": "de_anna_2", "title": "De Anna sermones II", "col": 643, "pages": [270, 278], "kind": "sections", "cut": True},
        {"slug": "de_anna_3", "title": "De Anna sermones III", "col": 651, "pages": [278, 286], "kind": "sections", "cut": True},
        {"slug": "de_anna_4", "title": "De Anna sermones IV", "col": 659, "pages": [286, 294], "kind": "sections", "cut": True},
        {"slug": "de_anna_5", "title": "De Anna sermones V", "col": 669, "pages": [295, 302], "kind": "sections"},
        {"slug": "de_davide_et_saule_1", "title": "De Davide et Saule homiliae I", "col": 675, "pages": [302, 311], "kind": "sections", "cut": True},
        {"slug": "de_davide_et_saule_2", "title": "De Davide et Saule homiliae II", "col": 687, "pages": [314, 319], "kind": "sections"},
        {"slug": "de_davide_et_saule_3", "title": "De Davide et Saule homiliae III", "col": 695, "pages": [322, 334], "kind": "sections"},
    ],
    55: [
        # S. Joannes Chrysostomus V/1: Expositio in Psalmos, spuria.  Main scan IA patrologiae_cursus_completus_gr_vol_055;
        # psalm titles that were not recognised in the OCR are kept with the preceding psalm (see the titles);
        # column = 2e + 35, re-anchored after the single Latin pages 147 and 554.
        {"slug": "in_psalmum_3", "title": "Expositio in Psalmum III", "col": 35, "pages": [28, 32], "kind": "sections"},
        {"slug": "in_psalmum_4_5", "title": "Expositio in Psalmos IV-V (later starts not recognised; one file)", "col": 39, "pages": [32, 64], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_6", "title": "Expositio in Psalmum VI", "col": 71, "pages": [64, 72], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_7_8", "title": "Expositio in Psalmos VII-VIII (later starts not recognised; one file)", "col": 79, "pages": [72, 113], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_9_10", "title": "Expositio in Psalmos IX-X (later starts not recognised; one file)", "col": 121, "pages": [113, 136], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_11_12", "title": "Expositio in Psalmos XI-XII (later starts not recognised; one file)", "col": 143, "pages": [136, 148], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_41_43", "title": "Expositio in Psalmos XLI, XLIII (later starts not recognised; one file)", "col": 155, "pages": [148, 173], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_44_45", "title": "Expositio in Psalmos XLIV-XLV (later starts not recognised; one file)", "col": 181, "pages": [173, 200], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_46_47", "title": "Expositio in Psalmos XLVI-XLVII (later starts not recognised; one file)", "col": 207, "pages": [200, 213], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_48_49_108", "title": "Expositio in Psalmos XLVIII-XLIX, CVIII (later starts not recognised; one file)", "col": 221, "pages": [213, 256], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_109", "title": "Expositio in Psalmum CIX", "col": 263, "pages": [256, 272], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_110", "title": "Expositio in Psalmum CX", "col": 279, "pages": [272, 281], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_111", "title": "Expositio in Psalmum CXI", "col": 289, "pages": [281, 292], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_112", "title": "Expositio in Psalmum CXII", "col": 299, "pages": [292, 296], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_113", "title": "Expositio in Psalmum CXIII", "col": 303, "pages": [296, 305], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_114_115", "title": "Expositio in Psalmos CXIV-CXV (later starts not recognised; one file)", "col": 315, "pages": [308, 320], "kind": "sections"},
        {"slug": "in_psalmum_116_117_119", "title": "Expositio in Psalmos CXVI-CXVII, CXIX (later starts not recognised; one file)", "col": 327, "pages": [320, 336], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_120_122", "title": "Expositio in Psalmos CXX-CXXII (later starts not recognised; one file)", "col": 343, "pages": [336, 344], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_123", "title": "Expositio in Psalmum CXXIII", "col": 353, "pages": [345, 348], "kind": "sections"},
        {"slug": "in_psalmum_124", "title": "Expositio in Psalmum CXXIV", "col": 355, "pages": [348, 352], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_125", "title": "Expositio in Psalmum CXXV", "col": 359, "pages": [352, 353], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_126", "title": "Expositio in Psalmum CXXVI", "col": 361, "pages": [353, 357], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_127", "title": "Expositio in Psalmum CXXVII", "col": 365, "pages": [357, 364], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_128", "title": "Expositio in Psalmum CXXVIII", "col": 371, "pages": [364, 364], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_129", "title": "Expositio in Psalmum CXXIX", "col": 373, "pages": [365, 368], "kind": "sections"},
        {"slug": "in_psalmum_130_131", "title": "Expositio in Psalmos CXXX-CXXXI (later starts not recognised; one file)", "col": 377, "pages": [369, 376], "kind": "sections"},
        {"slug": "in_psalmum_132", "title": "Expositio in Psalmum CXXXII", "col": 383, "pages": [376, 377], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_133", "title": "Expositio in Psalmum CXXXIII", "col": 385, "pages": [377, 380], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_134", "title": "Expositio in Psalmum CXXXIV", "col": 387, "pages": [380, 392], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_135_136", "title": "Expositio in Psalmos CXXXV-CXXXVI (later starts not recognised; one file)", "col": 399, "pages": [392, 400], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_137", "title": "Expositio in Psalmum CXXXVII", "col": 407, "pages": [400, 401], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_138", "title": "Expositio in Psalmum CXXXVIII", "col": 411, "pages": [404, 412], "kind": "sections"},
        {"slug": "in_psalmum_139_140", "title": "Expositio in Psalmos CXXXIX-CXL (later starts not recognised; one file)", "col": 419, "pages": [412, 433], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_141", "title": "Expositio in Psalmum CXLI", "col": 441, "pages": [433, 437], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_142_143", "title": "Expositio in Psalmos CXLII-CXLIII (later starts not recognised; one file)", "col": 445, "pages": [437, 456], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_144_145", "title": "Expositio in Psalmos CXLIV-CXLV (later starts not recognised; one file)", "col": 463, "pages": [456, 468], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_146", "title": "Expositio in Psalmum CXLVI", "col": 475, "pages": [468, 469], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_147_148", "title": "Expositio in Psalmos CXLVII-CXLVIII (later starts not recognised; one file)", "col": 477, "pages": [469, 484], "kind": "sections", "cut": True},
        {"slug": "in_psalmum_149", "title": "Expositio in Psalmum CXLIX", "col": 493, "pages": [485, 488], "kind": "sections"},
        {"slug": "in_psalmum_150", "title": "Expositio in Psalmum CL", "col": 495, "pages": [488, 509], "kind": "sections", "cut": True},
        {"slug": "spuria_in_psalmos_monitum_et_protheoria", "title": "Spuria in Psalmos: Latin monitum, protheoria and following pieces (cols. 517-548)", "col": 517, "pages": [509, 541], "kind": "sections", "cut": True},
        {"slug": "spuria_in_psalmum_13", "title": "Spuria: In Psalmum XIII and following pieces", "col": 549, "pages": [541, 585], "kind": "sections", "cut": True},
        {"slug": "spuria_in_illud_vovete_et_reddite", "title": "Spuria: Sermo in illud: Vovete et reddite (Ps 75) and following pieces", "col": 593, "pages": [585, 621], "kind": "sections", "cut": True},
        {"slug": "spuria_post_admonitionem", "title": "Spuria and dubia after the Latin admonitio (cols. 629-674)", "col": 629, "pages": [621, 668], "kind": "sections", "cut": True},
        {"slug": "spuria_in_psalmum_118", "title": "Spuria: In Psalmum CXVIII", "col": 675, "pages": [668, 776], "kind": "sections", "cut": True},
    ],
    94: [
        {"slug": "vita_joannis", "title": "Vita Joannis Damasceni (auctore Joanne Hierosolymitano)",
         "pages": [215, 256], "kind": "sections"},
        {"slug": "testimonia_veterum", "title": "Testimonia selecta veterum de S. Joanne Damasceno et eius scriptis",
         "pages": [257, 261], "kind": "sections"},
        # Fons scientiae (Pege gnoseos): Migne prints its three parts as separate works;
        # the dedication to Cosmas of Maiuma (p. 266) opens part I
        {"slug": "fons_scientiae_1_dialectica",
         "title": "Fons scientiae (Pege gnoseos), pars I: Dialectica (Capita philosophica)",
         "pages": [264, 355], "kind": "chapters"},
        {"slug": "fons_scientiae_2_de_haeresibus", "title": "Fons scientiae (Pege gnoseos), pars II: De haeresibus",
         "pages": [356, 407], "kind": "numbered"},
        {"slug": "fons_scientiae_3_expositio_fidei",
         "title": "Fons scientiae (Pege gnoseos), pars III: Expositio fidei (Ekdosis akribes tes orthodoxou pisteos)",
         "pages": [412, 633], "kind": "books"},
        {"slug": "orationes_de_imaginibus", "title": "Orationes de imaginibus I-III",
         "pages": [634, 739], "kind": "orations", "run_key": "ORATIO"},
        {"slug": "de_recta_sententia", "title": "De recta sententia", "pages": [740, 745], "kind": "sections"},
        {"slug": "contra_jacobitas", "title": "Contra Jacobitas", "pages": [746, 780], "kind": "numbered"},
        {"slug": "contra_manichaeos", "title": "Dialogus contra Manichaeos", "pages": [781, 823],
         "kind": "numbered_dialogue", "speakers": {"ΜΑΝ.": r"Μ[ΑΛ][ΝΒΕ]|ΚΑΝ|ΜΝ", "ΟΡΘ.": r"ΟΡ?Θ|Ο[ΕΞ]Θ|ΟΘΟΟΖ|ΟΕ"}},
        {"slug": "disputatio_saraceni", "title": "Disputatio Christiani et Saraceni", "pages": [824, 831],
         "kind": "dialogue", "speakers": {}},
        {"slug": "de_draconibus", "title": "De draconibus et strygibus", "pages": [832, 834], "kind": "sections"},
    ],
    95: [
        # "col": first Migne column (table of contents, checked on the page images)
        # "cut": the work starts under its title in the middle of the page (the text above
        # belongs to the previous work or is a Latin preface); a page shared with the next
        # work is split at the same title
        {"slug": "de_sancta_trinitate", "title": "De sancta Trinitate", "col": 9, "pages": [10, 14], "kind": "sections"},
        {"slug": "de_hymno_trisagio", "title": "Epistola de hymno Trisagio (ad Jordanem archimandritam)",
         "pages": [16, 36], "kind": "sections"},
        {"slug": "de_sacris_jejuniis", "title": "De sacris jejuniis", "col": 63, "pages": [37, 44], "kind": "sections",
         "cut": True},
        {"slug": "de_octo_spiritibus_nequitiae", "title": "De octo spiritibus nequitiae", "col": 79, "pages": [45, 48],
         "kind": "sections"},
        {"slug": "de_virtutibus_et_vitiis", "title": "De virtutibus et vitiis", "pages": [48, 54],
         "kind": "sections", "cut": True},
        {"slug": "institutio_elementaris", "title": "Institutio elementaris ad dogmata", "col": 99, "pages": [55, 61],
         "kind": "chapters"},
        {"slug": "contra_acephalos", "title": "De natura composita contra Acephalos", "col": 111, "pages": [61, 68],
         "kind": "sections", "cut": True},
        {"slug": "de_duabus_voluntatibus", "title": "De duabus in Christo voluntatibus", "col": 127, "pages": [69, 98],
         "kind": "chapters", "cut": True},
        {"slug": "contra_nestorianos", "title": "Dissertatio adversus Nestorianorum haeresim", "col": 187, "pages": [99, 123],
         "kind": "numbered"},
        {"slug": "fragmenta", "title": "Fragmenta (e codice S. Hilarii)", "col": 226, "pages": [124, 130], "kind": "sections"},
        {"slug": "epistola_quid_est_homo", "title": "Epistola de hoc: Quid est homo?", "col": 243, "pages": [133, 134],
         "kind": "sections"},
        {"slug": "de_his_qui_in_fide_dormierunt", "title": "Oratio de his qui in fide dormierunt",
         "col": 250, "pages": [135, 152], "kind": "sections"},
        {"slug": "epistola_de_confessione", "title": "Epistola de confessione", "col": 283, "pages": [155, 164],
         "kind": "sections"},
        {"slug": "adversus_constantinum_cabalinum", "title": "De sacris imaginibus adversus Constantinum Cabalinum",
         "col": 310, "pages": [168, 185], "kind": "sections"},
        {"slug": "epistola_ad_theophilum", "title": "Epistola ad Theophilum imperatorem de sacris imaginibus",
         "col": 346, "pages": [186, 206], "kind": "sections"},
        {"slug": "de_azymis", "title": "De azymis", "col": 387, "pages": [207, 211], "kind": "sections"},
        {"slug": "de_corpore_et_sanguine", "title": "De corpore et sanguine Christi (ad Zachariam)",
         "col": 402, "pages": [214, 219], "kind": "sections", "cut": True},
        {"slug": "fragmenta_dogmatica", "title": "Fragmenta dogmatica", "pages": [220, 221], "kind": "sections"},
        # Expositio in Epistolas Pauli (cols. 441-1034), one work per epistle
        {"slug": "in_romanos", "title": "Expositio in Epistolam ad Romanos", "col": 441, "pages": [236, 302],
         "kind": "chapters", "cut": True},
        {"slug": "in_1_corinthios", "title": "Expositio in Epistolam I ad Corinthios", "pages": [302, 372],
         "kind": "chapters", "cut": True},
        {"slug": "in_2_corinthios", "title": "Expositio in Epistolam II ad Corinthios", "pages": [372, 407],
         "kind": "chapters", "cut": True},
        {"slug": "in_galatas", "title": "Expositio in Epistolam ad Galatas", "pages": [407, 430],
         "kind": "chapters", "cut": True},
        {"slug": "in_ephesios", "title": "Expositio in Epistolam ad Ephesios", "pages": [430, 447],
         "kind": "chapters", "cut": True},
        {"slug": "in_philippenses", "title": "Expositio in Epistolam ad Philippenses", "pages": [447, 461],
         "kind": "chapters", "cut": True},
        {"slug": "in_colossenses", "title": "Expositio in Epistolam ad Colossenses", "pages": [461, 471],
         "kind": "chapters", "cut": True},
        {"slug": "in_thessalonicenses", "title": "Expositio in Epistolas I-II ad Thessalonicenses",
         "pages": [472, 484], "kind": "chapters"},
        {"slug": "in_hebraeos", "title": "Expositio in Epistolam ad Hebraeos", "pages": [484, 513],
         "kind": "chapters", "cut": True},
        {"slug": "in_timotheum_titum_philemonem", "title": "Expositio in Epistolas I-II ad Timotheum, ad Titum, ad Philemonem",
         "pages": [513, 531], "kind": "chapters", "cut": True},
        {"slug": "sacra_parallela", "title": "Sacra Parallela (pars prima, PG 95)", "pages": [534, 825],
         "kind": "sections", "cut": True},
    ],
    96: [
        # "col": first Migne column (table of contents, PDF p. 8; page = (col + 9) / 2 in this scan)
        {"slug": "sacra_parallela_continuatio", "title": "Sacra Parallela (continuatio)", "col": 9,
         "pages": [9, 238], "kind": "sections"},
        {"slug": "parallela_rupefucaldina", "title": "Excerpta ex Parallelis Rupefucaldinis", "col": 467,
         "pages": [238, 277], "kind": "sections", "cut": True},
        {"slug": "homiliae", "title": "Homiliae", "col": 545, "pages": [277, 412], "kind": "sections", "cut": True},
        {"slug": "precationes", "title": "Precationes tres", "col": 815, "pages": [412, 413], "kind": "sections",
         "cut": True},
        {"slug": "carmina", "title": "Carmina et cantica", "col": 818, "pages": [413, 432], "kind": "sections",
         "cut": True},
        # from here: supplement of the Patrologia editor (not in Lequien's edition)
        {"slug": "vita_barlaam_et_joasaph", "title": "Vita Barlaam et Joasaph", "col": 859, "pages": [434, 629],
         "kind": "sections"},
        {"slug": "passio_artemii", "title": "S. Artemii Passio", "col": 1249, "pages": [629, 664],
         "kind": "sections", "cut": True},
        {"slug": "disputatio_cum_manichaeo", "title": "Joannis Orthodoxi Disputatio cum Manichaeo", "col": 1319,
         "pages": [664, 672], "kind": "dialogue", "cut": True,
         "speakers": {"ΜΑΝ.": r"Μ[ΑΛ][ΝΒΕ]|ΚΑΝ|ΜΝ", "ΟΡΘ.": r"ΟΡ?Θ|Ο[ΕΞ]Θ|ΟΘΟΟΖ|ΟΕ"}},
        {"slug": "disputatio_saraceni", "title": "Disputatio Saraceni cum Christiano", "col": 1335,
         "pages": [672, 678], "kind": "dialogue", "speakers": {}, "cut": True},
        {"slug": "adversus_iconoclastas", "title": "Liber adversus Iconoclastas", "col": 1347, "pages": [678, 685],
         "kind": "sections", "cut": True},
        {"slug": "hymni", "title": "Hymni", "col": 1363, "pages": [686, 708], "kind": "sections"},
        {"slug": "fragmenta_in_matthaeum", "title": "Fragmenta in Matthaeum", "col": 1407, "pages": [708, 712],
         "kind": "sections", "cut": True},
        {"slug": "joannes_cp_ad_constantinum", "title": "Joannes CP. patriarcha: Epistola ad Constantinum papam",
         "col": 1415, "pages": [712, 722], "kind": "sections", "cut": True},
        {"slug": "joannes_nicaenus_de_nativitate", "title": "Joannes Nicaenus: De Nativitate Domini sermo",
         "col": 1435, "pages": [722, 729], "kind": "sections", "cut": True},
        {"slug": "joannes_euboeensis_in_conceptionem", "title": "Joannes Euboeensis: Sermo in Conceptionem Deiparae",
         "col": 1459, "pages": [734, 754], "kind": "sections"},
        {"slug": "joannes_euboeensis_in_innocentes", "title": "Joannes Euboeensis: Sermo in SS. Innocentes",
         "col": 1501, "pages": [755, 757], "kind": "sections"},
    ],
}


# Corrections of the main scan read from the running heads on the page images, where no
# independent second scan exists (PG 95: the IA "second scan" is the same digitisation).
#   order:   stretches of shuffled pages, each in its true sequence
#   cols:    left Migne column of single pages (anchors for the column count)
#   missing: Migne columns not contained in the scan (reported in coverage.txt)
#   in_order: the main scan is complete and in order (no reordering by the second scan)
#   same_scan: the second scan is the same digitisation (copies found by their text; column
#            numbers from sparse running heads of 2-4 digits, single changes confirmed by 3 of 4)
SCAN_FIXES = {
    # PG 96: main scan complete and in order (left column = 2 x page - 9 on every page, checked
    # on the running heads); the second scan's page map is only used for its text
    96: {"in_order": True},
    # PG 27: main scan in order (running heads); the IA "PatrologiaGraeca" copy has other
    # leaves and its own repeated pages, so it must not reorder the pages.  The pages the
    # scan contains twice are left out of the column count; p332/p333 (Ps. 1 twice, the
    # second time with the commentary) are different pages.
    27: {"in_order": True, "drop": [53, 54] + list(range(523, 533)) + list(range(673, 683))},
    # PG 28: main scan in order (running heads 2p - 15, then 2p - 19); pp. 407-408 repeat pp. 405-406
    28: {"in_order": True, "drop": [407, 408]},
    # PG 29: main scan in order; pp. 683-692 repeat pp. 673-682 (the IA "PatrologiaGraeca" copy
    # has its own extra leaves, so it must not reorder the pages)
    29: {"in_order": True, "drop": list(range(683, 693))},
    # PG 30: one scan (IA PatrologiaGraeca Vol. 030); two leaves are missing in it (running heads on
    # the page images: p361 = cols. 713-714, p362 = 719-720; p403 = 801-802, p404 = 807-808),
    # filled from the microfilm copy on archive.org (bim_early-english-books-1641-1700_1857_30,
    # left column = 2 x leaf - 5)
    30: {
        "in_order": True,
        "order": [[361, 20715, 20717, 362], [403, 20803, 20805, 404]],
        "cols": {362: 719, 404: 807},
        "missing": [("715-718 (De virginitate)", [20715, 20717]), ("803-806 (De virginitate)", [20803, 20805])],
        # the four leaves (360, 361, 404, 405 of the microfilm copy) as a 4-page PDF: border cropped,
        # contrast raised, and on leaves 360 and 404 (Latin left in that copy) the columns swapped
        "patch": {"pdf": "PG030_bim4c.pdf", "source": "archive.org bim_early-english-books-1641-1700_1857_30",
                  "pages": {20715: 1, 20717: 2, 20803: 3, 20805: 4}},
    },
    # PG 31: main scan in order; the pairs pp. 400-401, 576-577, 630-631, 818-819 repeat the two
    # pages before them (each step of 4 in the running heads)
    31: {"in_order": True, "drop": [400, 401, 576, 577, 630, 631, 818, 819],
         "cols": {90: 163, 402: 783, 578: 1131, 632: 1235, 820: 1607}},
    # PG 32: main scan in order; the pairs pp. 199-200, 265-266, 373-374, 639-640 repeat the two
    # pages before them (each step of 4 in the running heads)
    32: {"in_order": True, "drop": [199, 200, 265, 266, 373, 374, 639, 640],
         "cols": {39: 67, 201: 387, 267: 515, 375: 727, 641: 1255}},
    # PG 33: main scan in order; the pairs pp. 361-362, 565-566, 597-598 repeat the two pages before them
    33: {"in_order": True, "drop": [361, 362, 565, 566, 597, 598],
         "cols": {152: 293, 363: 711, 567: 1115, 599: 1175}},
    # PG 35: main scan in order; the pairs pp. 361-362 and 369-370 repeat the two pages before them
    35: {"in_order": True, "drop": [361, 362, 369, 370],
         "cols": {131: 243, 363: 703, 371: 715}},
    # PG 36: main scan in order; three blocks of ten pages photographed twice (excluded pages)
    36: {"in_order": True, "drop": list(range(38, 48)) + list(range(190, 200)) + list(range(508, 518)),
         "cols": {9: 9, 48: 67, 200: 351, 518: 967}},
    # PG 37: main scan in order, no repeated pages; left column = 2p - 11 throughout
    37: {"in_order": True, "drop": [], "cols": {16: 21}},
    # PG 38: main scan in order, no repeated pages; left column = 2p - 11 throughout
    38: {"in_order": True, "drop": [], "cols": {10: 9}},
    # PG 44: main scan in order; pp. 259-268 repeat pp. 249-258 (excluded pages)
    44: {"in_order": True, "drop": list(range(259, 269)), "cols": {38: 61, 269: 503},
         # p222 (cols. 429-430): two blocks of Greek set across the full width (end of the De vita Moysis),
         # missed by the layout model; transcribed from the page image (IA PatrologiaGraeca Vol. 44, leaf 220)
         "supply": [
             {"slug": "de_vita_moysis", "page": 222, "after": "πῶς ἂν ἁμαυρω",
              "text": "θήσεται διὰ τοῦ σκότους, οὗ ἠλλοτρίωται; καὶ ὁ τὴν ἀφθαρσίαν ἐν πάσῃ τῇ ζωῇ κατορθώσας, "
                      "οὐδεμίαν πάντως φθορὰν ἐφ´ ἑαυτοῦ παραδέχεται. Ὁ γὰρ ἀληθῶς κατ´ εἰκόνα Θεοῦ γεγονὼς, καὶ "
                      "μηδαμοῦ παρατραπεὶς τοῦ θείου χαρακτῆρος· ἐφ´ ἑαυτοῦ τὰ γνωρίσματα φέρει, καὶ συμβαίνει διὰ "
                      "πάντων τῇ ὁμοιώσει πρὸς τὸ ἀρχέτυπον, τῷ ἀφθάρτῳ τε καὶ ἀναλλοιώτῳ, καὶ πάσης ἀμιγεῖ κακίας "
                      "τὴν ἰδίαν ψυχὴν καλλωπίζων.\n\n"},
             {"slug": "de_vita_moysis", "page": 222, "after": "καὶ μόνον τίμιόν τε καὶ ἐράσμιον",
              "text": " ἑαυτοῖς κρῖναι, τὸ φίλον γενέσθαι Θεῷ· ὅπερ ἐστὶ, κατά γε τὸν ἐμὸν λόγον, ἡ τελειότης τοῦ "
                      "βίου. Ὅ τι δ´ ἂν παρὰ σοῦ πρὸς τὸ μεγαλοπρεπέστερόν τε καὶ θειότερον ἐπαρθείσης σοι τῆς "
                      "διανοίας, εὑρεθῇ· πολλῶν δὲ..... εὑρεθήσεται· κοινὸν ἔσται πάντως τὸ κέρδος, ἐν Χριστῷ Ἰησοῦ "
                      "τῷ Κυρίῳ ἡμῶν, ᾧ ἡ δόξα καὶ τὸ κράτος εἰς τοὺς αἰῶνας. Ἀμήν."},
         ]},
    # PG 45: main scan in order, no repeated pages; left column = 2p - 15 throughout
    45: {"in_order": True, "drop": [], "cols": {12: 9}},
    # PG 46: main scan in order, no repeated pages; left column = 2p - 15 throughout
    46: {"in_order": True, "drop": [], "cols": {13: 11}},
    # PG 47: Greek pages only (the Latin pages are excluded and dropped); anchors from the page heads
    47: {"in_order": True, "min_gap": 150,      # titles between works are small in this edition
         "drop": [34, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54, 56, 57, 58, 59, 60, 62, 63, 66, 67, 70, 71, 74, 75, 78, 79, 82, 83, 86, 87, 90, 91, 94, 95, 98, 99, 102, 103, 106, 107, 110, 111, 114, 115, 118, 119, 122, 123, 126, 127, 130, 131, 134, 135, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175, 176, 177, 178, 179, 180, 181, 182, 183, 184, 185, 186, 187, 188, 189, 190, 191, 192, 193, 194, 195, 196, 197, 198, 199, 200, 201, 202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 212, 213, 214, 215, 216, 217, 218, 219, 220, 221, 222, 223, 224, 225, 226, 227, 228, 229, 230, 231, 232, 233, 234, 235, 236, 238, 239, 242, 243, 246, 247, 250, 251, 254, 255, 258, 259, 262, 263, 266, 267, 270, 271, 274, 275, 277, 278, 279, 282, 283, 286, 287, 290, 291, 294, 295, 298, 299, 302, 303, 306, 307, 310, 311, 314, 315, 318, 319, 322, 323, 326, 327, 330, 331, 334, 335, 338, 339, 342, 343, 346, 347, 350, 351, 353, 354, 356, 357, 360, 361, 364, 365, 368, 369, 372, 373, 376, 377, 380, 381, 384, 385, 386, 388, 389, 392, 393, 396, 397, 400, 401, 404, 405, 408, 409, 412, 413, 416, 417, 420, 421, 424, 425, 428, 429, 432, 433, 436, 437, 440, 441, 444, 445, 448, 449, 452, 453, 456, 457, 460, 461, 464, 465, 468, 469, 472, 473, 476, 477, 480, 481, 484, 485, 488, 489, 492, 493, 495, 496, 497, 498, 499, 500],
         "cols": {33: 43, 61: 5, 237: 277, 280: 319, 309: 349, 355: 393, 374: 411, 383: 421, 387: 425,
                  410: 447, 458: 495, 475: 513}},
    # PG 48: Greek pages only (Latin pages excluded and dropped); anchors fitted to Migne columns
    48: {"in_order": True, "min_gap": 150,
         "drop": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 18, 19, 22, 23, 26, 27, 30, 31, 34, 35, 38, 39, 42, 43, 46, 47, 50, 51, 54, 55, 58, 59, 62, 63, 66, 67, 70, 71, 74, 75, 77, 78, 79, 82, 83, 86, 87, 90, 91, 94, 95, 98, 99, 101, 102, 103, 106, 107, 110, 111, 114, 115, 118, 119, 122, 123, 126, 127, 130, 131, 134, 135, 138, 139, 142, 143, 146, 147, 150, 151, 154, 155, 158, 159, 162, 163, 166, 167, 170, 171, 174, 175, 178, 179, 182, 183, 186, 187, 190, 191, 194, 195, 198, 199, 202, 203, 206, 207, 210, 211, 214, 215, 218, 219, 222, 223, 226, 227, 230, 231, 234, 235, 238, 239, 242, 243, 246, 247, 250, 251, 254, 255, 258, 259, 262, 263, 266, 267, 270, 271, 274, 275, 278, 279, 282, 283, 286, 287, 290, 291, 294, 295, 298, 299, 302, 303, 306, 307, 310, 311, 314, 315, 318, 319, 321, 322, 323, 326, 327, 330, 331, 334, 335, 338, 339, 342, 343, 346, 347, 350, 351, 354, 355, 358, 359, 362, 363, 366, 367, 370, 371, 374, 375, 378, 379, 382, 383, 386, 387, 390, 391, 394, 395, 398, 399, 402, 403, 406, 407, 410, 411, 414, 415, 418, 419, 422, 423, 424, 426, 427, 430, 431, 434, 435, 438, 439, 442, 443, 446, 447, 450, 451, 454, 455, 458, 459, 462, 463, 466, 467, 470, 471, 474, 475, 478, 479, 482, 483, 486, 487, 490, 491, 494, 495, 498, 499, 502, 503, 506, 507, 510, 511, 514, 515, 518, 519, 522, 523, 526, 527, 530, 531, 534, 535, 538, 539, 542, 543, 546, 547, 550, 551, 554, 555, 558, 559, 562, 563, 566, 567, 570, 571, 574, 575, 577, 578, 579, 580, 581, 582, 583, 584, 585, 586, 587, 588, 589, 590, 591, 592, 593, 594, 595, 596, 597, 598, 599, 600, 601],
         "cols": {13: 533, 80: 599, 104: 623, 324: 843, 425: 945}},
    # PG 49: Greek pages only (Latin pages excluded and dropped); anchors fitted to Migne columns
    49: {"in_order": True, "min_gap": 150,
         "drop": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 18, 19, 22, 23, 26, 27, 30, 31, 34, 35, 38, 39, 42, 43, 46, 47, 50, 51, 54, 55, 58, 59, 62, 63, 66, 67, 70, 71, 74, 75, 78, 79, 82, 83, 86, 87, 90, 91, 94, 95, 98, 99, 102, 103, 106, 107, 110, 111, 114, 115, 118, 119, 122, 123, 126, 127, 130, 131, 134, 135, 138, 139, 142, 143, 146, 147, 150, 151, 154, 155, 158, 159, 162, 163, 166, 167, 170, 171, 174, 175, 178, 179, 182, 183, 186, 187, 190, 191, 194, 195, 198, 199, 202, 203, 206, 207, 210, 211, 214, 215, 218, 219, 222, 223, 226, 227, 230, 231, 234, 235, 238, 239, 242, 243, 246, 247, 250, 251, 254, 255, 258, 259, 262, 263, 266, 267, 270, 274, 275, 278, 279, 282, 283, 286, 287, 290, 291, 294, 295, 298, 299, 302, 303, 306, 307, 310, 311, 314, 315, 318, 319, 322, 323, 326, 327, 330, 331, 334, 335, 338, 339, 342, 344, 346, 347, 350, 351, 354, 355, 358, 359, 362, 363, 366, 367, 370, 371, 374, 375, 378, 379, 382, 383, 386, 387, 390, 391, 394, 395, 398, 399, 402, 403, 406, 407, 410, 411, 412, 413, 414, 415],
         "cols": {16: 15, 224: 223, 241: 241, 273: 277, 345: 351, 357: 363, 368: 373, 388: 393, 393: 399}},
    # PG 50: Greek pages only (Latin pages excluded and dropped); anchors fitted to Migne columns
    50: {"in_order": True, "min_gap": 150,
         "drop": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 19, 20, 23, 24, 27, 28, 31, 32, 35, 36, 39, 40, 43, 44, 47, 48, 51, 52, 55, 56, 59, 60, 63, 64, 67, 69, 71, 72, 75, 76, 79, 80, 83, 84, 87, 88, 91, 92, 95, 96, 99, 100, 103, 104, 107, 108, 111, 112, 115, 116, 119, 120, 123, 124, 125, 127, 128, 131, 132, 135, 136, 139, 140, 143, 144, 147, 148, 151, 152, 155, 156, 159, 160, 163, 164, 167, 168, 171, 172, 175, 176, 179, 180, 182, 183, 184, 187, 188, 191, 192, 195, 196, 199, 200, 203, 204, 207, 208, 211, 212, 215, 216, 219, 220, 223, 224, 227, 228, 231, 232, 235, 236, 239, 240, 243, 244, 247, 248, 251, 252, 255, 256, 259, 260, 263, 264, 267, 268, 271, 272, 275, 276, 279, 280, 283, 284, 287, 288, 291, 292, 295, 296, 299, 300, 303, 304, 307, 308, 311, 312, 315, 316, 319, 320, 323, 324, 327, 328, 331, 332, 335, 336, 339, 340, 343, 344, 347, 348, 351, 352, 355, 356, 359, 360, 363, 364, 367, 368, 371, 372, 375, 376, 379, 380, 383, 384, 387, 388, 391, 392, 395, 396, 399, 400, 403, 404, 407, 408, 411, 412, 415, 416, 419, 420, 422, 423, 424, 425, 426, 427, 428, 429, 430, 431, 432, 433, 434, 435, 436, 437, 438, 439, 440, 441, 442],
         "cols": {14: 417, 126: 529, 185: 587}},
    # PG 51: Greek pages only (Latin pages, p233 and p264 excluded and dropped); one anchor: col = 2e + 17
    51: {"in_order": True, "min_gap": 150,
         "drop": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 21, 24, 25, 28, 29, 32, 33, 36, 37, 40, 41, 44, 45, 48, 49, 52, 53, 56, 57, 60, 61, 64, 65, 67, 70, 71, 74, 75, 78, 79, 82, 83, 86, 87, 90, 91, 94, 95, 98, 99, 102, 103, 106, 107, 110, 111, 114, 115, 118, 119, 122, 123, 126, 127, 130, 131, 134, 135, 138, 139, 142, 143, 146, 147, 150, 151, 154, 155, 158, 159, 162, 163, 166, 167, 170, 171, 174, 175, 178, 179, 182, 183, 186, 187, 190, 191, 194, 195, 198, 199, 202, 203, 206, 207, 210, 211, 214, 215, 218, 219, 222, 223, 226, 227, 230, 231, 233, 234, 236, 237, 240, 241, 244, 245, 248, 249, 252, 253, 256, 257, 260, 261, 263, 264, 266, 267, 270, 271, 274, 275, 278, 279, 282, 283, 286, 287, 290, 291, 294, 295, 298, 299, 302, 303, 306, 307, 310, 311, 314, 315, 318, 319, 322, 323, 326, 327, 330, 331, 334, 335, 338, 339, 342, 343, 346, 347, 350, 351, 354, 355, 358, 359, 362, 363, 366, 367, 370, 371, 374, 375, 378, 379, 382, 383, 386, 387, 390, 391, 393, 394, 395, 396, 397, 398, 399],
         "cols": {16: 17}},
    # PG 52: Greek pages only (Latin pages excluded and dropped); anchors from the page heads and known starts
    52: {"in_order": True, "min_gap": 150,
         "drop": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 19, 20, 23, 24, 27, 28, 31, 32, 35, 36, 39, 40, 43, 44, 46, 47, 48, 49, 50, 53, 54, 56, 57, 58, 61, 62, 63, 64, 67, 68, 71, 72, 75, 76, 79, 80, 83, 84, 87, 88, 91, 92, 95, 96, 99, 100, 103, 104, 107, 108, 111, 112, 115, 116, 119, 120, 123, 124, 127, 128, 131, 132, 135, 136, 139, 140, 143, 144, 147, 148, 151, 152, 155, 156, 159, 160, 161, 163, 164, 165, 166, 167, 169, 170, 173, 174, 177, 178, 181, 182, 185, 186, 189, 190, 193, 194, 197, 198, 201, 202, 205, 206, 209, 210, 213, 214, 217, 218, 221, 222, 225, 226, 229, 230, 233, 234, 237, 238, 241, 242, 245, 246, 249, 250, 253, 254, 257, 258, 261, 262, 265, 266, 269, 270, 273, 274, 277, 278, 281, 282, 285, 286, 289, 290, 293, 294, 297, 298, 299, 301, 302, 305, 306, 309, 310, 313, 314, 317, 318, 321, 322, 325, 326, 329, 330, 333, 334, 337, 338, 341, 342, 345, 346, 349, 350, 353, 354, 357, 358, 361, 362, 365, 366, 367, 368, 369, 370, 371, 372, 373, 375, 376, 379, 380, 383, 384, 387, 388, 391, 392, 395, 396, 399, 400, 403, 404, 407, 408, 411, 412, 415, 416, 419, 420, 423, 424, 427, 428, 431, 432, 435, 436, 439, 440, 443, 444, 447, 448, 451, 452, 455, 456, 459, 460, 462, 463, 464, 465, 466, 467, 468, 469, 470, 471, 472, 473, 474, 475, 476, 477, 478, 479, 480, 481, 482],
         "cols": {17: 391, 51: 427, 59: 435, 70: 449, 101: 479, 150: 529, 168: 549, 374: 757}},
    # PG 53: Greek pages only (Latin pages excluded and dropped)
    53: {"in_order": True, "min_gap": 150,
         "drop": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 24, 25, 28, 29, 32, 33, 36, 37, 40, 41, 44, 45, 48, 49, 52, 53, 56, 57, 60, 61, 64, 65, 68, 69, 72, 73, 76, 77, 80, 81, 84, 85, 88, 89, 92, 93, 96, 97, 100, 101, 104, 105, 108, 109, 112, 113, 116, 117, 120, 121, 124, 125, 128, 129, 132, 133, 136, 137, 140, 141, 144, 145, 148, 149, 152, 153, 156, 157, 160, 161, 164, 165, 168, 169, 172, 173, 176, 177, 180, 181, 184, 185, 188, 189, 192, 193, 196, 197, 200, 201, 204, 205, 208, 209, 212, 213, 216, 217, 220, 221, 224, 225, 228, 229, 232, 233, 236, 237, 240, 241, 244, 245, 248, 249, 252, 253, 256, 257, 260, 261, 264, 265, 268, 269, 272, 273, 276, 277, 280, 281, 284, 285, 288, 289, 292, 293, 296, 297, 300, 301, 304, 305, 308, 309, 312, 313, 316, 317, 320, 321, 324, 325, 328, 329, 332, 333, 336, 337, 340, 341, 344, 345, 348, 349, 352, 353, 356, 357, 360, 361, 364, 365, 368, 369, 372, 373, 376, 377, 380, 381, 384, 385, 387, 388, 389, 390, 391, 392, 393, 394, 395, 396, 397],
         "cols": {23: 21}},
    # PG 54: Greek pages only (Latin pages excluded and dropped)
    54: {"in_order": True, "min_gap": 150,
         "drop": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 16, 17, 20, 21, 24, 25, 28, 29, 32, 33, 36, 37, 40, 41, 44, 45, 48, 49, 52, 53, 56, 57, 60, 61, 64, 65, 68, 69, 72, 73, 76, 77, 80, 81, 84, 85, 88, 89, 92, 93, 96, 97, 100, 101, 104, 105, 108, 109, 112, 113, 116, 117, 120, 121, 124, 125, 128, 129, 132, 133, 136, 137, 140, 141, 144, 145, 148, 149, 152, 153, 156, 157, 160, 161, 164, 165, 168, 169, 172, 173, 176, 177, 180, 181, 184, 185, 188, 189, 192, 193, 196, 197, 200, 201, 204, 205, 208, 209, 212, 213, 216, 217, 220, 221, 224, 225, 228, 229, 232, 233, 236, 237, 240, 241, 244, 245, 248, 249, 252, 253, 256, 257, 260, 261, 264, 265, 268, 269, 272, 273, 276, 277, 280, 281, 284, 285, 288, 289, 292, 293, 296, 297, 300, 301, 304, 305, 308, 309, 312, 313, 316, 317, 320, 321, 324, 325, 328, 329, 332, 333, 335, 336, 337, 338, 339, 340, 341, 342, 343, 344, 345, 346, 347, 348, 349, 350, 351, 352, 353],
         "cols": {11: 385}},
    # PG 55: Greek pages only (Latin pages excluded and dropped)
    55: {"in_order": True, "min_gap": 150,
         "drop": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 30, 31, 34, 35, 38, 39, 42, 43, 46, 47, 50, 51, 54, 55, 58, 59, 62, 63, 66, 67, 70, 71, 74, 75, 78, 79, 82, 83, 86, 87, 90, 91, 94, 95, 98, 99, 102, 103, 106, 107, 110, 111, 114, 115, 118, 119, 122, 123, 126, 127, 130, 131, 134, 135, 138, 139, 142, 143, 147, 150, 151, 154, 155, 158, 159, 162, 163, 166, 167, 170, 171, 174, 175, 178, 179, 182, 183, 186, 187, 190, 191, 194, 195, 198, 199, 202, 203, 206, 207, 210, 211, 214, 215, 218, 219, 222, 223, 226, 227, 230, 231, 234, 235, 238, 239, 242, 243, 246, 247, 250, 251, 254, 255, 258, 259, 262, 263, 266, 267, 270, 271, 274, 275, 278, 279, 282, 283, 286, 287, 290, 291, 294, 295, 298, 299, 302, 303, 306, 307, 310, 311, 314, 315, 318, 319, 322, 323, 326, 327, 330, 331, 334, 335, 338, 339, 342, 343, 346, 347, 350, 351, 354, 355, 358, 359, 362, 363, 366, 367, 370, 371, 374, 375, 378, 379, 382, 383, 386, 387, 390, 391, 394, 395, 398, 399, 402, 403, 406, 407, 410, 411, 414, 415, 418, 419, 422, 423, 426, 427, 430, 431, 434, 435, 438, 439, 442, 443, 446, 447, 450, 451, 454, 455, 458, 459, 462, 463, 466, 467, 470, 471, 474, 475, 478, 479, 482, 483, 486, 487, 490, 491, 494, 495, 498, 499, 502, 503, 506, 507, 510, 511, 514, 515, 518, 519, 522, 523, 526, 527, 530, 531, 534, 535, 538, 539, 542, 543, 546, 547, 550, 551, 554, 558, 559, 562, 563, 566, 567, 570, 571, 574, 575, 578, 579, 582, 583, 586, 587, 590, 591, 594, 595, 598, 599, 602, 603, 606, 607, 610, 611, 614, 615, 618, 619, 622, 623, 626, 627, 630, 631, 634, 635, 638, 639, 642, 643, 646, 647, 650, 651, 654, 655, 658, 659, 662, 663, 666, 667, 670, 671, 674, 675, 678, 679, 682, 683, 686, 687, 690, 691, 694, 695, 698, 699, 702, 703, 706, 707, 710, 711, 714, 715, 718, 719, 722, 723, 726, 727, 730, 731, 734, 735, 738, 739, 742, 743, 746, 747, 750, 751, 754, 755, 758, 759, 762, 763, 766, 767, 770, 771, 774, 775, 777, 778, 779, 780, 781, 782, 783],
         "cols": {28: 35, 148: 155, 555: 561}},
    95: {
        "same_scan": True,      # no independent second scan: sparse running heads, copies by text
        # pages 2xxxx: Migne column xxxx from another copy (Google Books TM1DAQAAMAAJ), see
        # "patch" below; they are put in place by these sequences
        "order": [[490, 491, 501, 493, 494, 495, 492, 20955, 20957, 20959, 20961, 20963, 497, 498,
                   20969, 20971, 20973, 502],
                  [325, 20617, 20619, 326, 327, 330],
                  [618, 21209, 620, 21213, 622, 21217, 624, 21221, 626],
                  [653, 21257, 655, 656, 657, 654]],         # p654 holds cols. 1265-6 (p658 is its copy)
        "drop": [621],          # photographed blank (its column 1213 comes from the other copy)
        "cols": {326: 621, 490: 941, 501: 945, 492: 953, 497: 965, 502: 975,
                 620: 1211, 621: 1213, 622: 1215, 624: 1219, 626: 1223, 655: 1259, 654: 1265},
        "missing": [("617-620 (In I Cor.)", [20617, 20619]),
                    ("955-964 (In Hebr.)", [20955, 20957, 20959, 20961, 20963]),
                    ("969-974 (In Hebr.)", [20969, 20971, 20973]),
                    ("1209-1210 (Sacra Parallela)", [21209]),
                    ("1213-1214 (Sacra Parallela; page photographed blank)", [21213]),
                    ("1217-1218 (Sacra Parallela)", [21217]),
                    ("1221-1222 (Sacra Parallela)", [21221]),
                    ("1257-1258 (Sacra Parallela)", [21257])],
        # the missing pages in the other copy: PDF page there -> page id here
        "patch": {"pdf": "Patrologiae_cursus_completus_seu_Bibliot.pdf", "source": "Google Books TM1DAQAAMAAJ",
                  "pages": {20617: 318, 20619: 319, 20955: 487, 20957: 488, 20959: 489, 20961: 490,
                            20963: 491, 20969: 494, 20971: 495, 20973: 496, 21209: 614, 21213: 616,
                            21217: 618, 21221: 620, 21257: 638}},
    },
}


def patch_ids(vol):
    """Page ids 2xxxx: Migne column xxxx taken from another copy."""
    return set(SCAN_FIXES.get(vol, {}).get("patch", {}).get("pages", {}))


# ----------------------------------------------------------------- helpers
def gz_text(f):
    return gzip.decompress(f.read_bytes()).decode("utf-8", "replace")


def gz_json(f):
    return json.loads(gzip.decompress(f.read_bytes()))


def greek_words(text, n=7):
    t = unicodedata.normalize("NFD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower().replace("ς", "σ")
    return set(re.findall(r"[α-ω]{%d,}" % n, t))


HEAD_DIGITS = "3,4"


def head_numbers(text):
    """Column numbers in the running head (3-4 digits; 2-4 when the heads are sparse, so that
    the first columns of a volume (< 100) count too)."""
    return [int(x) for x in re.findall(r"(?<!\d)(\d{%s})(?!\d)" % HEAD_DIGITS, text[:160])]


def pdf_pages(args, best=None):
    """Number of pages of the main PDF (None if it cannot be read)."""
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        return len(fitz.open(str(args.pdf)))
    except Exception:
        try:
            out = subprocess.run(["pdfinfo", str(args.pdf)], capture_output=True, text=True).stdout
            return int(re.search(r"^Pages:\s+(\d+)", out, re.M).group(1))
        except Exception:
            return None


def main_scan_ocr(args, best):
    """IA OCR (running heads) of the main scan; empty if the item has none.

    Some Google scans on the Internet Archive (PG 95: patrologicursus50migngoog) carry no
    OCR; the column numbers then come from the running heads of the second scan alone."""
    n = pdf_pages(args, best)
    try:
        S.running_heads(args, max(best) + 20)      # downloads and caches the IA OCR
        mcache = args.root / "data" / "ia" / args.main_item
        text, index = gz_text(mcache / "searchtext.txt.gz"), gz_json(mcache / "pageindex.json.gz")
    except Exception as e:
        print(f"[works] no IA OCR for the main scan {args.main_item} ({e})", flush=True)
        text, index = "", None
    if index is not None and (n is None or len(index) == n):
        return text, index
    # the IA OCR counts other leaves than the PDF (PG 96: 796 entries, 792 PDF pages) or is
    # missing: use the PDF's own text layer, which is aligned page by page
    own = pdf_text_index(args)
    if own:
        if index is not None:
            print(f"[works] IA OCR has {len(index)} pages, the PDF {n}: running heads read from the "
                  f"PDF's text layer instead", flush=True)
        return own
    if index is not None:
        print(f"[works] IA OCR has {len(index)} pages, the PDF {n}, and the PDF has no text layer: "
              f"column numbers from the second scan only", flush=True)
    return "", [[0, 0]] * (n or max(p for p in best if p < 10000))


def pdf_text_index(args, min_share=0.5):
    """Text layer of the main PDF as (text, [start, end] per page), or None if it has none."""
    cache = args.root / "data" / "ia" / f"{args.main_item}_pdftext"
    st, pi = cache / "searchtext.txt.gz", cache / "pageindex.json.gz"
    if not (st.exists() and pi.exists()):
        try:
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz
            parts, index, pos, full = [], [], 0, 0
            for page in fitz.open(str(args.pdf)):
                t = " ".join(page.get_text().split()) + " "
                full += len(t) > 200
                parts.append(t)
                index.append([pos, pos + len(t)])
                pos += len(t)
        except Exception:
            return None
        if full < min_share * max(1, len(index)):
            return None
        cache.mkdir(parents=True, exist_ok=True)
        st.write_bytes(gzip.compress("".join(parts).encode("utf-8")))
        pi.write_bytes(gzip.compress(json.dumps(index).encode("utf-8")))
    return gz_text(st), gz_json(pi)


def title_gap(rec, min_gap=300):
    """Where a new work starts on a page: (gap start, gap end) in page pixels, or None.

    Works that begin in mid-page start under a title that the layout model often does not
    see as a whole, but the Greek text always breaks there: the text above and below the
    title are separate Greek boxes.  The gap chosen is the first one (also the one above
    the first box) that contains a detected title; else the largest gap between Greek
    boxes, if it is at least `min_gap` px."""
    if not rec or not rec.get("greek"):
        return None
    boxes = sorted((g["box"] for g in rec["greek"]), key=lambda b: b[1])
    titles = [d["box"] for d in rec.get("detections", []) if d["cls"] == "MainText_Title" and d["conf"] >= 0.25]
    gaps, prev = [], 0
    for b in boxes:
        gaps.append((prev, b[1]))
        prev = max(prev, b[3])
    gaps.append((prev, rec["size"][1]))          # a title below the last box: nothing follows it
    for a, b in gaps:
        if any(a - 20 <= (t[1] + t[3]) / 2 <= b + 20 for t in titles):
            return (a, b)
    inner = [(b - a, a, b) for a, b in gaps[1:-1] if b - a >= min_gap]
    return (max(inner)[1], max(inner)[2]) if inner else None


ALPHA_START = re.compile(r"^\s*[αΑ]\s?[ʹ΄'’`]\s*[.·]?\s")
TITLE_WORD = re.compile(r"ΟΜΙΛΙ|ΛΟΓΟΣ|ΕΓΚΩΜΙ|^\W*ΕΙΣ\s|^\W*ΠΕΡΙ\s|^\W*ΚΑΤΑ\s|^\W*ΤΟΥ\s+ΑΥΤΟΥ")


def text_cut(items):
    """Where a new work starts on a page, from the recognised text, when title_gap finds no gap:
    the first Greek block that begins with an upper-case title line (ΟΜΙΛΙΑ, ΛΟΓΟΣ, ΕΓΚΩΜΙΟΝ,
    ΕΙΣ ...) or with the opening "αʹ." of a homily.  Returns the block's top y, or None.  Only a
    block that begins with such a line can be cut at (the y split works on whole blocks)."""
    first = {}
    for it in items:
        if it["kind"] == "line" and (it["col"] not in first or it["n"] < first[it["col"]]["n"]):
            first[it["col"]] = it
    cands = []
    for it in first.values():
        t = it["text"].strip()
        letters = [c for c in t if c.isalpha()]
        upper = letters and sum(c.isupper() for c in letters) / len(letters) > 0.6
        if (upper and TITLE_WORD.search(t)) or ALPHA_START.match(t):
            cands.append(it["y"])
    return min(cands) if cands else None


TITLE_START = re.compile(r"^\W*(Εἰ?ς\s|Είς\s|ΕΙΣ\s|Περὶ\s|ΠΕΡΙ\s|Λόγος|ΛΟΓΟΣ|Ὁμιλία|ΟΜΙΛΙΑ|Πρὸς\s|ΠΡΟΣ\s|Κατὰ\s|ΚΑΤΑ\s)")


def text_cut_index(items):
    """(1.31) Where a new work starts inside a column, from the recognised lines: the position in
    reading order (left column, then right) of the opening "αʹ." line, moved back over up to four
    title lines before it (Εἰς τὸ ..., Περὶ ..., Λόγος ..., upper case) and the "Ἀμήν." that
    ends the previous work.  Returns an index into items, or None."""
    for k, it in enumerate(items):
        if it["kind"] == "line" and ALPHA_START.match(it["text"]) and k > 0:
            j = k
            for i in range(k - 1, max(-1, k - 5), -1):
                t = items[i].get("text", "") if items[i]["kind"] == "line" else "T"
                if items[i]["kind"] == "block" or TITLE_START.match(t):
                    j = i
                elif "Ἀμήν" in t or "Ἀμὴν" in t:
                    break
            prev = " ".join(x.get("text", "") for x in items[max(0, j - 3):j])
            if j < k or "Ἀμήν" in prev:
                return j
    # no "αʹ." recognised: the line after the "Ἀμήν." that closes the previous work
    for k, it in enumerate(items[:-1]):
        if it["kind"] == "line" and re.search(r"Ἀμήν\.?\s*$", it["text"]):
            return k + 1
    return None


# ----------------------------------------------------------------- 1: order and duplicates
def page_words(lines):
    return set(re.findall(r"\w{5,}", " ".join(l[3] for l in lines)))


def order_pages(pages, best, altmap, report, max_jump=20, dup_jaccard=0.7, known_dups=None, text_jaccard=None):
    """Sort pages by their leaf in the second scan; drop second copies of a page.

    A page's own leaf is trusted only if it lies within max_jump leaves of what its
    neighbours predict (a wrongly matched page keeps its PDF position)."""
    matched = sorted((p, v["leaf"] - p) for p, v in altmap.items() if v["how"] == "matched")

    def expected_leaf(p):
        near = sorted(matched, key=lambda x: abs(x[0] - p))[:9]
        if not near:
            return p
        offs = sorted(o for _, o in near)
        return p + offs[len(offs) // 2]

    keyleaf, dropped, distrusted = {}, dict(known_dups or {}), []
    for p in pages:
        v = altmap.get(p)
        exp = expected_leaf(p)
        if v and v["how"] == "extra":
            keyleaf[p] = v["leaf"]              # a leaf added from the second scan
        elif v and v["how"] == "matched" and abs(v["leaf"] - exp) <= max_jump:
            keyleaf[p] = v["leaf"]
        else:
            keyleaf[p] = exp
            if v and v["how"] == "matched":
                distrusted.append(p)
    # second copies: same leaf and (nearly) the same text
    by_leaf = collections.defaultdict(list)
    for p in pages:
        if p not in dropped:
            by_leaf[keyleaf[p]].append(p)
    for leaf, ps in by_leaf.items():
        ps = sorted(ps, key=lambda p: (-len(best.get(p, [])), p))
        for p in ps[1:]:
            a, b = page_words(best.get(ps[0], [])), page_words(best.get(p, []))
            # same leaf and same text, or an empty page (a copy the merge already removed)
            trusted = altmap.get(p, {}).get("how") == "matched" and p not in distrusted
            if a and ((b and len(a & b) / len(a | b) >= dup_jaccard) or (not b and trusted)):
                dropped[p] = ps[0]
    # copies the second scan cannot show (PG 95: the "second scan" is the same digitisation,
    # with the same re-scanned pages): a page whose text largely repeats a page 2-14 pages
    # before it is a second copy; the first occurrence stands in the right place
    kept = [p for p in pages if p not in dropped] if text_jaccard else []
    words = {p: page_words(best.get(p, [])) for p in kept}
    for i, p in enumerate(kept):
        if p in dropped or len(words[p]) < 40:
            continue
        for q in kept[i + 1:i + 15]:
            if q in dropped or len(words[q]) < 40 or not 2 <= q - p <= 14:
                continue
            if len(words[p] & words[q]) / len(words[p] | words[q]) >= text_jaccard:
                dropped[q] = p
    order = sorted((p for p in pages if p not in dropped), key=lambda p: (keyleaf[p], p))
    moved = sum(1 for a, b in zip(order, order[1:]) if b < a)
    report.append(f"page order: {moved} places where the scan order was corrected; "
                  f"{len(distrusted)} page(s) kept in PDF position (doubtful match: "
                  f"{', '.join('p%d' % p for p in distrusted) or '-'})")
    report.append(f"{len(dropped)} second copies of a page dropped: "
                  + (", ".join(f"p{a}=p{b}" for a, b in sorted(dropped.items())) or "-"))
    return order, dropped


# ----------------------------------------------------------------- 2: coverage
def coverage(best, altmap, alt_text, alt_index, lo, hi):
    """Greek leaves of the second scan whose words are not found on any page."""
    vocab = collections.Counter()
    page_words = {}
    for p, lines in best.items():
        w = greek_words(" ".join(l[3] for l in lines))
        page_words[p] = w
        vocab.update(w)
    inv = collections.defaultdict(set)
    for p, w in page_words.items():
        for x in w:
            inv[x].add(p)
    used = {v["leaf"] for v in altmap.values()}
    missing = []
    for leaf in range(lo, min(hi, len(alt_index) - 1) + 1):
        a = alt_index[leaf]
        real = [x for x in greek_words(alt_text[a[0]:a[1]]) if vocab[x] >= 2]
        if len(real) < 80:
            continue                        # Latin page, plate or little Greek
        hits = collections.Counter()
        for x in real:
            for p in inv[x]:
                hits[p] += 1
        p, n = hits.most_common(1)[0]
        if n / len(real) < 0.4:
            missing.append((leaf, leaf in used, len(real), round(n / len(real), 2)))
    return missing


# ----------------------------------------------------------------- 3: columns
def page_votes(p, k, main_text, main_index, alt_text, alt_index, altmap):
    """Votes for the offset c in 'left column = 2k + c' from the running heads of page p."""
    nums = []
    if p - 1 < len(main_index):
        a = main_index[p - 1]
        nums += head_numbers(main_text[a[0]:a[1]])
    v = altmap.get(p)
    if v and v["leaf"] < len(alt_index):
        a = alt_index[v["leaf"]]
        nums += head_numbers(alt_text[a[0]:a[1]])
    c = collections.Counter()
    for n in nums:
        for m in ([n, n + 600] if 100 <= n < 200 else [n]):   # ABBYY often reads the 7 of 7xx as 1
            c[m - 2 * k] += 1
            c[m - 1 - 2 * k] += 1
    return c


def fit_columns_ordered(order, main_text, main_index, alt_text, alt_index, altmap, window=5, confirm=3, reach=60,
                        anchors=None, exact=(), sparse=False):
    """Left Migne column of every page, from the running heads of both scans.

    The offset c in 'left column = 2k + c' (k = position in the corrected order) is
    constant while no page is missing; a page missing from the scan raises c by 2.
    Such steps are accepted when `confirm` following pages agree on the new value.
    Returns (columns, steps) with steps = [(page before, page after, pages missing)]."""
    own = []
    for k, p in enumerate(order):
        v = page_votes(p, k, main_text, main_index, alt_text, alt_index, altmap)
        best = v.most_common(2)
        # a page's own value counts if it is supported twice (left+right number, or both scans)
        own.append(best[0][0] if best and best[0][1] >= 2 and (len(best) == 1 or best[0][1] > best[1][1]) else None)
    # starting value: the first value that `confirm` successive readable heads agree on
    # (front matter and plates before the text have no usable running heads)
    seen = [x for x in own if x is not None]
    start = next((seen[i] for i in range(len(seen) - confirm + 1)
                  if all(x == seen[i] for x in seen[i:i + confirm])), seen[0] if seen else 0)
    cur, cols, steps = None, {}, []
    anchors = anchors or {}
    for k, p in enumerate(order):
        if cur is None:
            if sparse:
                cur = start
            else:
                vals = [x for x in own[k:k + 2 * window] if x is not None]
                cur = collections.Counter(vals).most_common(1)[0][0] if vals else 0
            if p in anchors:
                cur = anchors[p] - 2 * k
        elif p in anchors:
            # a work's first column from the volume's table of contents (the left or the
            # right column of its first page), or a page's left column read on the image
            c = min((anchors[p] - 2 * k, anchors[p] - 1 - 2 * k), key=lambda x: abs(x - cur)) \
                if p not in exact else anchors[p] - 2 * k
            if c != cur:
                steps.append((order[k - 1] if k else p, p, (c - cur) // 2))
                cur = c
        elif sparse and own[k] is not None and own[k] != cur and abs(own[k] - cur) <= 60:
            # `confirm` of the next confirm+1 readable heads (within `reach` pages; heads are
            # sparse when only one scan has OCR) must agree on the new value; misread
            # numbers far from the current value are ignored
            ahead = [x for x in own[k:k + reach] if x is not None and abs(x - cur) <= 60][:confirm + 1]
            if ahead.count(own[k]) >= confirm:
                steps.append((order[k - 1], p, (own[k] - cur) // 2))
                cur = own[k]
        elif not sparse and own[k] is not None and own[k] != cur:
            ahead = [x for x in own[k:k + confirm + 2] if x is not None][:confirm]
            if len(ahead) == confirm and all(x == own[k] for x in ahead):
                steps.append((order[k - 1], p, (own[k] - cur) // 2))
                cur = own[k]
        cols[p] = (2 * k + cur, 2 * k + cur + 1)
    return cols, steps


def gap_leaves(steps, altmap, used, is_copy):
    """Split column steps into real gaps (unused, non-duplicate leaves of the second scan
    lie between the two pages) and mere corrections of the column count."""
    gaps, corrections = [], []
    for before, after, n in steps:
        la, lb = altmap.get(before, {}).get("leaf"), altmap.get(after, {}).get("leaf")
        cand = [l for l in range(la + 1, lb) if l not in used and not is_copy(l)] \
            if n > 0 and la is not None and lb is not None and lb > la + 1 else []
        if cand:
            gaps.append((before, after, n, cand[:n]))
        else:
            corrections.append((before, after, n))
    return gaps, corrections


# ----------------------------------------------------------------- 4: works
def section_heads(order, items_of):
    """Title blocks on the Greek side as section headings (not numbered)."""
    heads = []
    for p in order:
        for k, it in enumerate(items_of[p]):
            if it["kind"] != "block":
                continue
            good = [t.strip() for t, c in it["lines"] if c >= 0.85 and len(t.strip()) >= 4]
            if good:                            # unreadable title blocks are left out
                heads.append({"page": p, "k": k, "text": " ".join(good)})
    return heads


NUM_RX = re.compile(r"^(?:⟦\?⟧\s*)?[«(\[]?\s*([α-ωϛϟ]{1,3})\s?[ʹ'΄´]\s?[.,·]\s*(.*)$")


def numbered_heads(order, items_of, report, max_step=4, gap_cost=0.6):
    """Sections numbered in the text ('βʹ. Σκυθισμός ...', 'ιʹ. Εἰ μερικὰς ...').

    Every line that starts with a Greek numeral is a candidate; the longest increasing
    chain with small steps is kept (dynamic programming), so OCR-garbled numerals and
    sub-lists that restart at 1 (e.g. the Messalian propositions) do not break it."""
    cand = []
    for p in order:
        for k, it in enumerate(items_of[p]):
            if it["kind"] != "line":
                continue
            m = NUM_RX.match(it["text"].strip())
            if m:
                v = S.greek_number(m.group(1))
                if v:
                    cand.append((p, k, v, m.group(2)))
    n = len(cand)
    if not n:
        return []
    score, back = [1.0] * n, [-1] * n
    for j in range(n):
        for i in range(max(0, j - 60), j):
            d = cand[j][2] - cand[i][2]
            if 1 <= d <= max_step and score[i] + 1 - gap_cost * (d - 1) > score[j]:
                score[j], back[j] = score[i] + 1 - gap_cost * (d - 1), i
    j = max(range(n), key=lambda x: score[x])
    chain = []
    while j >= 0:
        chain.append(cand[j])
        j = back[j]
    chain.reverse()
    heads, prev = [], 0
    for p, k, v, rest in chain:
        if v > prev + 1:
            report.append(f"number(s) {prev + 1}-{v - 1} not found before PDF p. {p}")
        name = re.split(r"(?<=[^\s]{3})[·.,;:]", rest, maxsplit=1)[0][:60].strip()
        heads.append({"page": p, "k": k, "text": f"{S.greek_ord(v)}. {name}".strip(), "no": v,
                      "keep_line": True})
        prev = v
    report.append(f"{len(heads)} numbered sections (1-{prev}) out of {n} numeral-like line starts")
    return heads


def oration_of_page(main_text, main_index, key, pages):
    """Oration number per page from running heads such as 'DE IMAGINIBUS ORATIO III.'"""
    raw = {}
    for p in pages:
        if p - 1 < len(main_index):
            a = main_index[p - 1]
            m = re.search(key + r"\s*([IVXLlT1H]{1,4})\b", main_text[a[0]:a[0] + 160])
            if m:
                v = S.roman_to_int(m.group(1).replace("H", "II"))
                if v:
                    raw[p] = v
    out, last = {}, 1
    for p in pages:
        near = [raw[q] for q in pages if abs(q - p) <= 4 and q in raw]
        if near:
            v = collections.Counter(near).most_common(1)[0][0]
            if v >= last:
                last = v
        out[p] = last
    return out


def build_sections(order, items_of, heads, cols, mark_conf, oration=None):
    hk = {(h["page"], h["k"]): h for h in heads}
    secs = []
    cur = {"head": None, "items": [], "page": order[0] if order else None, "col": None, "book": None}
    last_or = None
    for p in order:
        for k, it in enumerate(items_of[p]):
            col = cols.get(p, (None, None))[0 if it["side"] in ("L", "W") else 1]
            if oration and oration.get(p) != last_or:
                secs.append(cur)
                last_or = oration.get(p)
                cur = {"head": None, "items": [], "page": p, "col": col, "book": last_or}
            if (p, k) in hk:
                h = hk[(p, k)]
                secs.append(cur)
                cur = {"head": h["text"], "items": [], "page": p, "col": col,
                       "book": last_or, "no": h.get("no")}
                if not h.get("keep_line"):
                    continue
            if it["kind"] == "block":
                continue
            cur["items"].append({"kind": "line", "text": it["text"], "unsure": it["conf"] < mark_conf,
                                 "col": col, "page": p})
    secs.append(cur)
    return [s for s in secs if s["head"] is not None or s["items"]]


def speaker_breaks(paras, speakers):
    """Start a new paragraph at every speaker label (MAN. / ORTH.), normalised."""
    if not speakers:
        return paras
    alts = "|".join(f"(?P<s{i}>{pat})" for i, pat in enumerate(speakers.values()))
    names = list(speakers)
    rx = re.compile(r"(?:(?<=\s)|^)(?:" + alts + r")\.\s")
    out = []
    for para in paras:
        pieces, last = [], 0
        for m in rx.finditer(para):
            name = names[[i for i in range(len(names)) if m.group(f"s{i}")][0]]
            if m.start() > last:
                pieces.append(para[last:m.start()].strip())
            pieces.append(f"**{name}**")
            last = m.end()
        pieces.append(para[last:].strip())
        merged, buf = [], ""
        for x in pieces:
            if x.startswith("**") and x.endswith("**"):
                if buf:
                    merged.append(buf)
                buf = x + " "
            else:
                buf += x
        if buf.strip():
            merged.append(buf.strip())
        out += [m for m in merged if m]
    return out


SUPPLIED = []      # (slug, page, words) of the text supplied by SCAN_FIXES "supply", for coverage.txt


def apply_supply(vol, slug, paras):
    """Lines the layout model misses (Greek set across the whole page width below the two columns, e.g.
    at the end of a work) are supplied from SCAN_FIXES[vol]["supply"], transcribed from the page image:
    each entry inserts "text" right after the first occurrence of "after" in the work."""
    out = []
    whole = " ".join(paras)
    for f in SCAN_FIXES.get(vol, {}).get("supply", []):
        # already read by the OCR (pg_ocr_volume >= 3.5 reads Greek set across the full width)
        if f["slug"] == slug and f["text"].strip()[:25] in whole:
            f["_done"] = f["_read"] = True
    for p in paras:
        for f in SCAN_FIXES.get(vol, {}).get("supply", []):
            if f["slug"] == slug and not f.get("_done") and f["after"] in p:
                p = p.replace(f["after"], f["after"] + f["text"], 1)
                f["_done"] = True
                SUPPLIED.append((slug, f["page"], len(f["text"].split())))
        out.append(p)
    return out


def write_work(w, units, outdir, vol, mark, mode):
    d = outdir / w["slug"]
    (d / "sections").mkdir(parents=True, exist_ok=True)
    for f in (d / "sections").glob("*.txt"):
        f.unlink()
    md = [f"# {w['title']}", "",
          f"Migne, PG {vol}, PDF pp. {w['pages'][0]}-{w['pages'][1]}. [col. N] = start of Migne column N. "
          f"⟦?⟧ = uncertain line. Uncorrected OCR.", ""]
    rows = ["no\tbook\theading\tpdf_page\tmigne_col\twords"]
    last_book, n = None, 0
    for u in units:
        paras = S.paragraphs(u["items"], mark)
        paras = speaker_breaks(paras, w.get("speakers"))
        paras = apply_supply(vol, w["slug"], paras)
        if u.get("book") and u["book"] != last_book:
            label = {"books": "Liber", "orations": "Oratio"}.get(mode, "Pars")
            md += [f"## {label} {u['book']}", ""]
            last_book = u["book"]
        head = u["head"] if isinstance(u["head"], str) else (" ".join(u["head"]) if u["head"] else None)
        cite = f"PG {vol}, {u['col']}" if u.get("col") else f"PDF p. {u['page']}"
        if head:
            n += 1
            md += [f"### {head}  ({cite})", ""]
        elif paras:
            md += [f"### [{'beginning' if n == 0 else 'continued'}]  ({cite})", ""]
        md += [p + "\n" for p in paras]
        words = sum(len(p.split()) for p in paras)
        no = u.get("no") or n
        rows.append(f"{no}\t{u.get('book') or ''}\t{head or ''}\t{u['page']}\t{u.get('col') or ''}\t{words}")
        if paras:
            (d / "sections" / f"{len(rows) - 1:03d}.txt").write_text(
                (head or "[untitled]") + f"\n({cite})\n\n" + "\n\n".join(paras) + "\n", encoding="utf-8")
    (d / f"{w['slug']}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (d / "sections.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return len(rows) - 1


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vol", type=int, required=True)
    ap.add_argument("--root", type=Path, default=Path("/mnt/e/PG_OCR"))
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--text-tag", default="best")
    ap.add_argument("--works", type=Path, default=None, help="JSON list of works (default: built-in table)")
    ap.add_argument("--only", default=None, help="comma-separated work slugs")
    ap.add_argument("--main-item", default=None)
    ap.add_argument("--alt-run", default=None,
                    help="run of the second scan (v5: Internet Archive item; v6: local PDF); default: the one with an altmap")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--mark-conf", type=float, default=0.80)
    ap.add_argument("--mark", default="⟦?⟧ ")
    ap.add_argument("--no-titles", action="store_true")
    args = ap.parse_args()
    tag = f"PG{args.vol:03d}"
    args.main_item = args.main_item or S.MAIN_ITEMS.get(args.vol)
    args.pdf = args.root / "data" / "pdf" / f"{tag}.pdf"
    works = json.loads(args.works.read_text()) if args.works else WORKS.get(args.vol)
    if not works:
        sys.exit(f"no table of works for PG {args.vol}: give --works")
    all_table = list(works)
    if args.only:
        keep = set(args.only.split(","))
        works = [w for w in works if w["slug"] in keep]
    print(f"pg_works.py version {VERSION}", flush=True)

    out = args.root / "output" / tag / args.text_tag
    best = S.load_best(out / f"{tag}_lines.tsv")
    base = {}
    rep = out / "merge_report.tsv"
    if rep.exists():
        for row in rep.read_text(encoding="utf-8").splitlines()[1:]:
            f = row.split("\t")
            base[int(f[0])] = f[1]
    runs = sorted(set(base.values())) or ["v4"]
    for p in best:
        base.setdefault(p, runs[0])
    layouts = {}
    for r in runs:
        lf = args.root / "work" / tag / r / "layout.jsonl"
        layouts[r] = {}
        if lf.exists():
            for l in lf.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    d = json.loads(l)
                    layouts[r][d["page"]] = d
    # the second scan: the Internet Archive item (run v5, OCR in data/alt/) or a local PDF of
    # another copy (run v6, --source pdf2, its text layer in data/pdf2/PGxxx_<file>/)
    alt_run = args.alt_run or next((r for r in ("v5", "v6")
                                    if (args.root / "work" / tag / r / "altmap.json").exists()), "v5")
    amf = args.root / "work" / tag / alt_run / "altmap.json"
    altmap = {int(k): v for k, v in json.loads(amf.read_text()).items() if not k.startswith("_")} \
        if amf.exists() else {}

    main_text, main_index = main_scan_ocr(args, best)
    acache = args.root / "data" / "alt" / tag
    if alt_run != "v5" or not (acache / "searchtext.txt.gz").exists():
        cand = sorted((args.root / "data" / "pdf2").glob(f"{tag}_*/searchtext.txt.gz"))
        if cand:
            acache = cand[0].parent
    if (acache / "searchtext.txt.gz").exists():
        print(f"[works] second scan: run {alt_run}, text from {acache.relative_to(args.root)}", flush=True)
        alt_text, alt_index = gz_text(acache / "searchtext.txt.gz"), gz_json(acache / "pageindex.json.gz")
    else:
        # one scan only (PG 30): no second scan to check the page order and coverage with
        print("[works] no second scan: page order and columns from the main scan alone", flush=True)
        alt_text, alt_index = "", []

    report = []
    # the whole volume is ordered (also pages without Greek), so that column numbers
    # can be counted page by page; the works then take their pages from this order
    n_pdf = len(main_index)
    fixes = SCAN_FIXES.get(args.vol, {})
    same = bool(fixes.get("same_scan"))
    global HEAD_DIGITS
    HEAD_DIGITS = "2,4" if same else "3,4"
    known = {}
    # pages left out as copies: by the merge, or (one digitisation only) by one of the runs
    # for a page that has no text in the merged result either
    for r in [args.text_tag] + (runs if same else []):
        sf = args.root / "output" / tag / r / "summary.json"
        if sf.exists():
            for d in json.loads(sf.read_text()).get("duplicate_pages_skipped", []):
                a, b = d.split(" = ")
                a, b = int(a[1:]), int(b[1:])
                if r == args.text_tag or a not in best:
                    known.setdefault(a, b)
    # pages the second-scan run already recognised as a copy of an earlier page (PG 25: pairs
    # of pages photographed twice, e.g. p199-200 = p197-198)
    for p, v in altmap.items():
        m = re.match(r"duplicate of p(\d+)", str(v.get("how", "")))
        if m and p not in best:
            known.setdefault(p, int(m.group(1)))
    extra = sorted(p for p in best if p > n_pdf)        # leaves added from the second scan
    order, dropped = order_pages(list(range(1, n_pdf + 1)) + extra, best,
                                 {} if fixes.get("in_order") else altmap, report, known_dups=known,
                                 text_jaccard=0.25 if same else None)
    drop = [p for p in fixes.get("drop", []) if p in order]
    if drop:
        order = [p for p in order if p not in drop]
        report.append(f"left out (blank or unusable page): {', '.join('p%d' % p for p in drop)}")
    for seq in fixes.get("order", []):
        seq = [p for p in seq if p in order]
        if seq:
            at = min(order.index(p) for p in seq)
            rest = [p for p in order if p not in seq]
            order = rest[:at] + seq + rest[at:]
            report.append(f"page order fixed from the running heads: {', '.join('p%d' % p for p in seq)}")
    anchors = {w["pages"][0]: w["col"] for w in all_table if w.get("col")}
    anchors.update(fixes.get("cols", {}))
    anchors.update({p: p - 20000 for p in patch_ids(args.vol) if p in order})
    cols, steps = fit_columns_ordered(order, main_text, main_index, alt_text, alt_index, altmap, anchors=anchors,
                                      exact=set(fixes.get("cols", {})) | patch_ids(args.vol), sparse=same)
    vocab_pages = collections.defaultdict(set)
    for p, lines in best.items():
        for x in greek_words(" ".join(l[3] for l in lines)):
            vocab_pages[x].add(p)

    def is_copy(leaf):
        """True if most Greek words of this leaf are found together on one of our pages."""
        a = alt_index[leaf]
        w = [x for x in greek_words(alt_text[a[0]:a[1]]) if x in vocab_pages]
        if len(w) < 10:
            return True                     # hardly any Greek: not a missing Greek page
        hits = collections.Counter(p for x in w for p in vocab_pages[x])
        return hits.most_common(1)[0][1] / len(w) >= 0.4
    gaps, corrections = gap_leaves(steps, altmap, {v["leaf"] for v in altmap.values()}, is_copy)
    # a work runs from the position of its first page to the position of its last page in
    # the corrected order (a page misplaced in the scan goes with the work it belongs to)
    pos = {p: i for i, p in enumerate(order)}

    def position(p, last=False):
        cand = [q for q in pos if (q >= p if not last else q <= p)]
        q = min(cand) if not last else max(cand)
        return pos[q]
    work_pages = {}
    for w in works:
        a, b = position(w["pages"][0]), position(w["pages"][1], last=True)
        work_pages[w["slug"]] = [p for p in order[a:b + 1] if p in best]
    order = [p for p in order if p in best and any(p in v for v in work_pages.values())]
    leaves = [altmap[p]["leaf"] for p in order if p in altmap]
    missing = coverage({p: best[p] for p in order}, {p: altmap[p] for p in order if p in altmap},
                       alt_text, alt_index, min(leaves), max(leaves)) if leaves else []

    titles = {} if args.no_titles else S.ocr_titles(args, layouts, base, order)
    items_of = {p: S.page_items(p, best, layouts, base, titles) for p in order}
    for p in (int(x) for x in os.environ.get("PG_WORKS_DEBUG_PAGES", "").split(",") if x.strip()):
        for it in items_of.get(p, []):
            t = it.get("text") or " / ".join(x for x, _ in it.get("lines", []))
            print(f"DBG p{p} {it['kind'][0]} {it['side']} z{it['zone']} y{it['y']} c{it['col']} n{it['n']}: {t[:70]}")
    ia_main = {i + 1: main_text[a[0]:a[1]] for i, a in enumerate(main_index)}
    ia_alt = {p: alt_text[alt_index[v["leaf"]][0]:alt_index[v["leaf"]][1]]
              for p, v in altmap.items() if v["leaf"] < len(alt_index)}

    wdir = out.parent / "works"
    wdir.mkdir(parents=True, exist_ok=True)
    summary = ["slug\ttitle\tpdf_pages\tmigne_cols\tunits\tlines"]
    all_works = all_table
    for w in works:
        wp = work_pages[w["slug"]]
        if not wp:
            report.append(f"{w['slug']}: no pages")
            continue
        wrep = []
        kind = w["kind"]
        # a work that starts under its title in mid-page, and a page shared with the next work
        items_w = dict(items_of)
        first, last = w["pages"]
        if w.get("cut") and first in items_w:
            g = title_gap(layouts.get(base.get(first), {}).get(first), SCAN_FIXES.get(args.vol, {}).get("min_gap", 300))
            if g:
                # the text below the title; title blocks inside the gap are section headings
                # of a work in sections, but not chapter headings
                lo = g[1] if kind in ("books", "chapters") else g[0]
                items_w[first] = [it for it in items_of[first] if it["y"] >= lo]
            elif (lo := text_cut(items_of[first])) is not None:
                items_w[first] = [it for it in items_of[first] if it["y"] >= lo]
                wrep.append(f"p{first}: work starts at the block opening with its title / αʹ (y {lo})")
            elif (k := text_cut_index(items_of[first])) is not None:
                items_w[first] = items_of[first][k:]
                wrep.append(f"p{first}: work starts at the title / αʹ line inside a column (line {k})")
            elif len(layouts.get(base.get(first), {}).get(first, {}).get("greek", [])) > 1:
                wrep.append(f"p{first}: no break before the work's title found - whole page kept")
        i = next((j for j, x in enumerate(all_works) if x["slug"] == w["slug"]), None)
        nxt = all_works[i + 1] if i is not None and i + 1 < len(all_works) else None
        if nxt and nxt.get("cut") and nxt["pages"][0] == last and last in items_w:
            g = title_gap(layouts.get(base.get(last), {}).get(last), SCAN_FIXES.get(args.vol, {}).get("min_gap", 300))
            if g:
                items_w[last] = [it for it in items_of[last] if it["y"] < g[0]]
            elif (lo := text_cut(items_of[last])) is not None:
                items_w[last] = [it for it in items_of[last] if it["y"] < lo]
            elif (k := text_cut_index(items_of[last])) is not None:
                items_w[last] = items_of[last][:k]
            else:
                wrep.append(f"p{last}: shared with the next work, no break found - whole page kept in both")
        items_of_all, items_of = items_of, items_w
        if kind in ("books", "chapters"):
            books = S.fit_books(S.running_heads(args, max(best) + 20), wp) if kind == "books" else {p: 1 for p in wp}
            heads = S.resolve_headings(wp, items_of, ia_main, ia_alt, wrep)
            S.number_headings(heads, books, wrep)
            units = S.build_chapters(wp, items_of, heads, cols, args.mark_conf)
            if kind == "chapters":
                for u in units:
                    u["book"] = None
        elif kind in ("numbered", "numbered_dialogue"):
            heads = numbered_heads(wp, items_of, wrep)
            units = build_sections(wp, items_of, heads, cols, args.mark_conf)
        else:
            heads = section_heads(wp, items_of)
            oration = oration_of_page(main_text, main_index, w.get("run_key", "ORATIO"), wp) \
                if kind == "orations" else None
            units = build_sections(wp, items_of, heads, cols, args.mark_conf, oration)
        n = write_work(w, units, wdir, args.vol, args.mark, kind)
        c0 = cols.get(wp[0], ("?",))[0]
        c1 = cols.get(wp[-1], ("?", "?"))[1]
        nlines = sum(len(best[p]) for p in wp)
        summary.append(f"{w['slug']}\t{w['title']}\t{w['pages'][0]}-{w['pages'][1]}\t{c0}-{c1}\t{n}\t{nlines}")
        (wdir / w["slug"] / "report.txt").write_text(
            f"{w['title']}\nPDF pp. {w['pages'][0]}-{w['pages'][1]}, Migne cols. {c0}-{c1}\n"
            f"{n} {'chapters' if kind in ('books', 'chapters') else 'sections'}\n\n" + "\n".join(wrep or ["-"]) + "\n",
            encoding="utf-8")
        print(f"[works] {w['slug']:26s} pp. {w['pages'][0]}-{w['pages'][1]}  cols. {c0}-{c1}  {n} units", flush=True)
        items_of = items_of_all

    (wdir / "works.tsv").write_text("\n".join(summary) + "\n", encoding="utf-8")
    cov = [f"pg_works.py {VERSION}", ""] + report + ["",
           "Gaps in the Migne column sequence (running heads):"]
    for before, after, n, leaves in gaps:
        cov.append(f"  between p{before} and p{after}: {n} page(s) missing in the main scan; "
                   f"second-scan leaves to add: {','.join(map(str, leaves))}")
    if not gaps:
        cov.append("  none")
    if corrections:
        cov.append("  (column count re-synchronised at: "
                   + ", ".join(f"p{a}/p{b} ({n:+d})" for a, b, n in corrections) + ";"
                   + " + = pages missing in the scan, or a page without running head; - = an extra"
                   " page, e.g. a plate or table)")
    if fixes.get("missing"):
        still = [m for m, ids in fixes["missing"] if not all(p in best for p in ids)]
        filled = [m for m, ids in fixes["missing"] if all(p in best for p in ids)]
        if still:
            cov += ["", "Migne columns missing in the scan (checked on the page images; another copy of",
                    f"PG {args.vol} is needed for them):"] + [f"  cols. {m}" for m in still]
        if filled:
            src = fixes.get("patch", {}).get("source", "another copy")
            cov += ["", f"Migne columns missing in the scan, filled from {src}:"] + [f"  cols. {m}" for m in filled]
        pm = fixes.get("patch", {})
        if still and pm:
            todo = {p: q for p, q in pm["pages"].items() if p not in best}
            cov += ["", "To fill them (the other copy in data/pdf/), then merge and run this step again:",
                    f"  PDF_FILE=$PG_ROOT/data/pdf/{pm['pdf']} RUN=patch bash pg_ocr.sh {args.vol} map:"
                    + ",".join(f"{p}={q}" for p, q in sorted(todo.items())),
                    f"  bash pg_ocr.sh {args.vol} merge v4,v5+patch"]
    add = [l for _, _, _, leaves in gaps for l in leaves]
    if add:
        cov += ["", "To add them, then merge and run this step again:",
                f"  SOURCE=alt RUN=v5 bash pg_ocr.sh {args.vol} leaf:" + ",".join(map(str, add)),
                f"  bash pg_ocr.sh {args.vol} merge v4,v5"]
    sup = SCAN_FIXES.get(args.vol, {}).get("supply", [])
    if sup:
        cov += ["", "Text supplied by hand from the page image (lines the layout model missed, SCAN_FIXES \"supply\"):"]
        cov += [f"  {f['slug']}: p{f['page']}, {len(f['text'].split())} words after \"...{f['after'][-30:]}\""
                + ("  - not needed: the OCR has read it" if f.get("_read") else "" if f.get("_done")
                   else "  - NOT APPLIED (anchor not found)") for f in sup]
    cov += ["", "Greek leaves of the second scan whose words are found on no page (check):"]
    cov += [f"  alt leaf {l} (matched to a page: {u}; {n} Greek words; best overlap {o})"
            for l, u, n, o in missing] or ["  none"]
    (wdir / "coverage.txt").write_text("\n".join(cov) + "\n", encoding="utf-8")
    print("\n".join(cov))
    print(f"-> {wdir}")


if __name__ == "__main__":
    main()

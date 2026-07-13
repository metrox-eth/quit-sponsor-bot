#!/usr/bin/env python3
"""Quit-sponsor Telegram bot, private beta v0.

Single process, long polling, no dependencies beyond the standard library.
The sponsor brain is the open protocol (SKILL.md + SAFETY.md) as system
prompt, inference via the Virtuals compute router. One data directory per
user: logbook.jsonl (every event, timestamped) + profile.json (consent,
settings). Export and delete are real and one command each (ETHICS.md).
"""
import json
import os
import sys
import time
import threading
import urllib.request
from datetime import datetime, date
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'
SKILL_DIR = Path(os.environ.get('SKILL_DIR', '')) if os.environ.get('SKILL_DIR') else Path(__file__).resolve().parent.parent / 'quit-sponsor'
CONTEXT_TURNS = 40          # recent logbook lines fed back to the model
ANCHOR_HOUR = 21            # evening close, server local time


def load_secrets():
    env = {}
    f = BASE / 'secrets.env'
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env


SECRETS = load_secrets()
TG_TOKEN = SECRETS.get('TELEGRAM_BOT_TOKEN', '')
MODEL = SECRETS.get('SPONSOR_MODEL', 'z-ai-glm-5-turbo')
BETA_CAP = int(SECRETS.get('BETA_CAP', '20'))
LLM_URL = SECRETS.get('LLM_URL', 'https://compute.virtuals.io/v1/chat/completions')


def load_llm_key():
    if SECRETS.get('LLM_API_KEY'):
        return SECRETS['LLM_API_KEY']
    try:
        # operator convenience: claude-code-router config, if present
        cfg = json.load(open(os.path.expanduser('~/.claude-code-router/config.json')))
        return (cfg.get('Providers') or cfg.get('providers'))[0]['api_key']
    except Exception:
        sys.exit('LLM_API_KEY missing in secrets.env')


LLM_KEY = load_llm_key()

BOT_PREAMBLE = (
    "You are the quit-smoking sponsor defined by the two documents above, "
    "operating as a Telegram bot in a private beta. The person you are talking "
    "to accepted the beta terms (adult, not medical advice, crisis lines named). "
    "Persistent memory: the recent logbook is in the conversation below; keep "
    "your receipts exact and never invent log entries. Match the person's "
    "language. Plain text only, no markdown headers. Crisis replies short and "
    "fast. You cannot initiate contact except the evening close the person "
    "enabled; design around that honestly."
)

FALLBACK = (
    "I can't reach my brain right now - a technical failure on my side, not "
    "yours, and nothing you wrote is lost. If this is a crisis moment, do not "
    "wait on me: findahelpline.com has a human line for your country, and your "
    "local emergency number works at any hour. I'll answer as soon as I'm back."
)

WELCOME = (
    "Welcome. Before anything else, the honest ground rules:\n\n"
    "1. I am an AI sponsor running a published, open protocol. Peer-style "
    "support, informed by research.\n"
    "2. I am NOT a doctor and NOT an emergency service. Physical red flags go "
    "to a doctor; if you are in danger or acute distress, use your local "
    "emergency number or findahelpline.com, never wait on me.\n"
    "3. Adults only (18+).\n"
    "4. Your data: our exchanges and your logbook are stored on the operator's "
    "server. /export sends you everything, /delete erases everything, both "
    "for real. Replies are generated through privacy-first inference "
    "(/about names the current model). No ads, no selling data, no training "
    "on your content.\n"
    "5. Full texts: /terms and /ethics.\n\n"
    "If you are an adult and you agree, reply: agree"
)

CONSENTED = (
    "You're in, and the logbook is open.\n\n"
    "Where are you with smoking? One tap, or your own words - both work. "
    "For what it's worth: quitting on the spot, when the decision is yours, "
    "holds about 2.6x better than picking a future date."
)

ONB_KEYBOARD = {'inline_keyboard': [
    [{'text': "I'm quitting right now", 'callback_data': 'onb:now'}],
    [{'text': 'I already quit, holding on', 'callback_data': 'onb:holding'}],
    [{'text': 'Still thinking about it', 'callback_data': 'onb:thinking'}],
]}

ONB_MAP = {
    'onb:now': "I'm quitting right now. Today.",
    'onb:holding': "I already quit recently and I'm holding on so far.",
    'onb:thinking': "I'm still thinking about quitting. Not decided yet.",
}

# ---------- localization of fixed strings (the brain adapts on its own) ----------

FR = {
    'WELCOME': (
        "Bienvenue. Avant tout, les règles honnêtes du jeu :\n\n"
        "1. Je suis un parrain IA qui applique un protocole publié et ouvert. "
        "Du soutien de pair, informé par la recherche.\n"
        "2. Je ne suis PAS un médecin ni un service d'urgence. Un symptôme "
        "physique inquiétant se montre à un médecin ; en cas de danger ou de "
        "détresse aiguë, appelle ton numéro d'urgence local ou "
        "findahelpline.com, n'attends jamais après moi.\n"
        "3. Adultes uniquement (18+).\n"
        "4. Tes données : nos échanges et ton livre de bord sont stockés sur "
        "le serveur de l'opérateur. /export t'envoie tout, /delete efface "
        "tout, pour de vrai. Les réponses passent par une inférence dont le "
        "modèle est nommé dans /about. Pas de pub, pas de vente de données, "
        "pas d'entraînement sur tes contenus.\n"
        "5. Textes complets : /terms et /ethics (en anglais pour l'instant).\n\n"
        "Si tu es adulte et d'accord, réponds : j'accepte"
    ),
    'CONSENTED': (
        "C'est bon, ton livre de bord est ouvert.\n\n"
        "Où en es-tu avec la cigarette ? Un bouton, ou tes propres mots, les "
        "deux marchent. Pour info : arrêter sur-le-champ, quand la décision "
        "vient de toi, tient environ 2,6 fois mieux que se fixer une date."
    ),
    'HELP': (
        "/about - modèle actuel, confidentialité, le protocole\n"
        "/terms - conditions de la bêta\n"
        "/ethics - la charte qui engage les opérateurs\n"
        "/export - recevoir ton livre de bord complet\n"
        "/delete - tout effacer (demande confirmation)\n"
        "/anchors on|off - message du soir (21h heure serveur)\n"
        "/report <problème> - signaler un souci à l'opérateur\n\n"
        "Pour tout le reste : parle-moi, simplement."
    ),
    'WAITLIST': (
        "La bêta privée est pleine : chacune de ses %d places mérite une "
        "vraie attention, et je préfère bien servir peu de monde que mal "
        "servir beaucoup. Tu es sur la liste d'attente ; ce chat recevra un "
        "message dès qu'une place se libère.\n\n"
        "Si tu arrêtes maintenant et que ça ne peut pas attendre : "
        "findahelpline.com liste du soutien humain pour ton pays, et le "
        "protocole ouvert que j'applique est libre : "
        "github.com/metrox-eth/quit-sponsor."
    ),
    'FALLBACK': (
        "Je n'arrive pas à joindre mon cerveau, panne technique de mon côté, "
        "pas du tien, et rien de ce que tu as écrit n'est perdu. Si c'est un "
        "moment de crise, ne m'attends pas : findahelpline.com a une ligne "
        "humaine pour ton pays, et ton numéro d'urgence local répond à toute "
        "heure. Je reviens dès que possible."
    ),
    'ONB_BUTTONS': [
        [{'text': "J'arrête maintenant", 'callback_data': 'onb:now'}],
        [{'text': "J'ai déjà arrêté, je tiens", 'callback_data': 'onb:holding'}],
        [{'text': "J'y réfléchis encore", 'callback_data': 'onb:thinking'}],
    ],
    'ONB_MAP': {
        'onb:now': "J'arrête de fumer maintenant. Aujourd'hui.",
        'onb:holding': "J'ai arrêté récemment et je tiens pour l'instant.",
        'onb:thinking': "J'y réfléchis encore. Pas encore décidé.",
    },
    'DELETE_ASK': "Ceci efface ton livre de bord, ton profil, tout, pour de "
                  "vrai. Réponds exactement : DELETE",
    'DELETE_DONE': "C'est fait. Tout est effacé. Si tu reviens un jour, ça "
                   "coûte un mot, et je repars de zéro.",
    'DELETE_CANCEL': "Suppression annulée. Rien n'a été effacé.",
    'REPORT_ACK': "Enregistré et transmis à l'opérateur. Merci, c'est comme "
                  "ça que la bêta s'améliore.",
    'ANCHOR': "Clôture du soir. Un mot suffit : tenu ?",
    'EXPORT_EMPTY': "Ton livre de bord est encore vide.",
    'EXPORT_CAPTION': "Ton livre de bord. À toi, entièrement.",
}

ES = {
    'WELCOME': (
        "Bienvenido. Antes de nada, las reglas honestas del juego:\n\n"
        "1. Soy un padrino de IA que sigue un protocolo publicado y abierto. "
        "Apoyo entre pares, informado por la investigación.\n"
        "2. NO soy un médico ni un servicio de emergencias. Un síntoma físico "
        "preocupante se enseña a un médico; en caso de peligro o angustia "
        "aguda, llama a tu número de emergencias local o findahelpline.com, "
        "nunca me esperes a mí.\n"
        "3. Solo adultos (18+).\n"
        "4. Tus datos: nuestras conversaciones y tu diario se guardan en el "
        "servidor del operador. /export te lo envía todo, /delete lo borra "
        "todo, de verdad. Las respuestas pasan por el modelo indicado en "
        "/about. Sin publicidad, sin venta de datos, sin entrenar con tus "
        "contenidos.\n"
        "5. Textos completos: /terms y /ethics (en inglés por ahora).\n\n"
        "Si eres adulto y estás de acuerdo, responde: acepto"
    ),
    'CONSENTED': (
        "Listo, tu diario está abierto.\n\n"
        "¿En qué punto estás con el tabaco? Un botón o tus propias palabras, "
        "ambos valen. Un dato: dejarlo en el acto, cuando la decisión es "
        "tuya, se mantiene unas 2,6 veces mejor que fijar una fecha."
    ),
    'HELP': (
        "/about - modelo actual, privacidad, el protocolo\n"
        "/terms - condiciones de la beta\n"
        "/ethics - la carta que obliga a los operadores\n"
        "/export - recibir tu diario completo\n"
        "/delete - borrarlo todo (pide confirmación)\n"
        "/anchors on|off - mensaje de cierre del día (21h del servidor)\n"
        "/report <problema> - avisar al operador\n\n"
        "Para todo lo demás: háblame, sin más."
    ),
    'WAITLIST': (
        "La beta privada está llena: cada una de sus %d plazas merece "
        "atención real, y prefiero atender bien a pocos que mal a muchos. "
        "Estás en la lista de espera; este chat recibirá un mensaje en "
        "cuanto se libere una plaza.\n\n"
        "Si lo estás dejando ahora y no puede esperar: findahelpline.com "
        "lista apoyo humano para tu país, y el protocolo abierto que sigo "
        "es libre: github.com/metrox-eth/quit-sponsor."
    ),
    'FALLBACK': (
        "No consigo conectar con mi cerebro: fallo técnico mío, no tuyo, y "
        "nada de lo que escribiste se ha perdido. Si es un momento de "
        "crisis, no me esperes: findahelpline.com tiene una línea humana "
        "para tu país, y tu número de emergencias local responde a "
        "cualquier hora. Vuelvo en cuanto pueda."
    ),
    'ONB_BUTTONS': [
        [{'text': 'Lo dejo ahora mismo', 'callback_data': 'onb:now'}],
        [{'text': 'Ya lo dejé, aguantando', 'callback_data': 'onb:holding'}],
        [{'text': 'Aún me lo pienso', 'callback_data': 'onb:thinking'}],
    ],
    'ONB_MAP': {
        'onb:now': 'Dejo de fumar ahora mismo. Hoy.',
        'onb:holding': 'Lo dejé hace poco y aguanto por ahora.',
        'onb:thinking': 'Aún me lo estoy pensando. No lo he decidido.',
    },
    'DELETE_ASK': 'Esto borra tu diario, tu perfil, todo, de verdad. '
                  'Responde exactamente: DELETE',
    'DELETE_DONE': 'Hecho. Todo borrado. Si algún día vuelves, cuesta una '
                   'palabra, y empiezo de cero.',
    'DELETE_CANCEL': 'Borrado cancelado. No se ha borrado nada.',
    'REPORT_ACK': 'Registrado y enviado al operador. Gracias: así mejora la beta.',
    'ANCHOR': 'Cierre del día. Una palabra basta: ¿aguantaste?',
    'EXPORT_EMPTY': 'Tu diario aún está vacío.',
    'EXPORT_CAPTION': 'Tu diario. Tuyo, por completo.',
}

PT = {
    'WELCOME': (
        "Bem-vindo. Antes de tudo, as regras honestas do jogo:\n\n"
        "1. Sou um padrinho de IA que segue um protocolo publicado e aberto. "
        "Apoio entre pares, informado pela pesquisa.\n"
        "2. NÃO sou médico nem serviço de emergência. Um sintoma físico "
        "preocupante vai ao médico; em caso de perigo ou sofrimento agudo, "
        "ligue para o número de emergência local ou findahelpline.com, "
        "nunca espere por mim.\n"
        "3. Somente adultos (18+).\n"
        "4. Seus dados: nossas conversas e seu diário ficam no servidor do "
        "operador. /export envia tudo, /delete apaga tudo, de verdade. As "
        "respostas passam pelo modelo indicado em /about. Sem anúncios, sem "
        "venda de dados, sem treinar com seu conteúdo.\n"
        "5. Textos completos: /terms e /ethics (em inglês por enquanto).\n\n"
        "Se você é adulto e concorda, responda: concordo"
    ),
    'CONSENTED': (
        "Pronto, seu diário está aberto.\n\n"
        "Em que ponto você está com o cigarro? Um botão ou suas próprias "
        "palavras, os dois funcionam. Um dado: parar na hora, quando a "
        "decisão é sua, dura cerca de 2,6 vezes mais do que marcar uma data."
    ),
    'HELP': (
        "/about - modelo atual, privacidade, o protocolo\n"
        "/terms - condições da beta\n"
        "/ethics - a carta que obriga os operadores\n"
        "/export - receber seu diário completo\n"
        "/delete - apagar tudo (pede confirmação)\n"
        "/anchors on|off - mensagem de fim de dia (21h do servidor)\n"
        "/report <problema> - avisar o operador\n\n"
        "Para todo o resto: fale comigo, simplesmente."
    ),
    'WAITLIST': (
        "A beta privada está cheia: cada uma das %d vagas merece atenção de "
        "verdade, e prefiro atender poucos bem do que muitos mal. Você está "
        "na lista de espera; este chat receberá uma mensagem assim que uma "
        "vaga abrir.\n\n"
        "Se você está parando agora e não pode esperar: findahelpline.com "
        "lista apoio humano para o seu país, e o protocolo aberto que sigo "
        "é livre: github.com/metrox-eth/quit-sponsor."
    ),
    'FALLBACK': (
        "Não consigo acessar meu cérebro agora: falha técnica minha, não "
        "sua, e nada do que você escreveu se perdeu. Se este é um momento "
        "de crise, não espere por mim: findahelpline.com tem uma linha "
        "humana para o seu país, e o número de emergência local atende a "
        "qualquer hora. Volto assim que puder."
    ),
    'ONB_BUTTONS': [
        [{'text': 'Vou parar agora', 'callback_data': 'onb:now'}],
        [{'text': 'Já parei, estou segurando', 'callback_data': 'onb:holding'}],
        [{'text': 'Ainda estou pensando', 'callback_data': 'onb:thinking'}],
    ],
    'ONB_MAP': {
        'onb:now': 'Vou parar de fumar agora. Hoje.',
        'onb:holding': 'Parei há pouco e estou segurando por enquanto.',
        'onb:thinking': 'Ainda estou pensando. Não decidi.',
    },
    'DELETE_ASK': 'Isto apaga seu diário, seu perfil, tudo, de verdade. '
                  'Responda exatamente: DELETE',
    'DELETE_DONE': 'Feito. Tudo apagado. Se um dia voltar, custa uma '
                   'palavra, e eu começo do zero.',
    'DELETE_CANCEL': 'Exclusão cancelada. Nada foi apagado.',
    'REPORT_ACK': 'Registrado e encaminhado ao operador. Obrigado: é assim '
                  'que a beta melhora.',
    'ANCHOR': 'Fechamento do dia. Uma palavra basta: segurou?',
    'EXPORT_EMPTY': 'Seu diário ainda está vazio.',
    'EXPORT_CAPTION': 'Seu diário. Seu, por inteiro.',
}

DE = {
    'WELCOME': (
        "Willkommen. Zuerst die ehrlichen Spielregeln:\n\n"
        "1. Ich bin ein KI-Pate, der einem veröffentlichten, offenen "
        "Protokoll folgt. Unterstützung auf Augenhöhe, gestützt auf "
        "Forschung.\n"
        "2. Ich bin KEIN Arzt und KEIN Notdienst. Besorgniserregende "
        "körperliche Symptome gehören zum Arzt; bei Gefahr oder akuter Not "
        "ruf deine lokale Notrufnummer an oder findahelpline.com, warte "
        "nie auf mich.\n"
        "3. Nur für Erwachsene (18+).\n"
        "4. Deine Daten: unsere Gespräche und dein Logbuch liegen auf dem "
        "Server des Betreibers. /export schickt dir alles, /delete löscht "
        "alles, wirklich. Antworten laufen über das in /about genannte "
        "Modell. Keine Werbung, kein Datenverkauf, kein Training mit "
        "deinen Inhalten.\n"
        "5. Volltexte: /terms und /ethics (vorerst auf Englisch).\n\n"
        "Wenn du erwachsen und einverstanden bist, antworte: einverstanden"
    ),
    'CONSENTED': (
        "Gut, dein Logbuch ist offen.\n\n"
        "Wo stehst du mit dem Rauchen? Ein Knopf oder deine eigenen Worte, "
        "beides geht. Übrigens: sofort aufzuhören, wenn die Entscheidung "
        "deine ist, hält etwa 2,6-mal besser als ein geplantes Datum."
    ),
    'HELP': (
        "/about - aktuelles Modell, Datenschutz, das Protokoll\n"
        "/terms - Beta-Bedingungen\n"
        "/ethics - die Charta, die die Betreiber bindet\n"
        "/export - dein vollständiges Logbuch erhalten\n"
        "/delete - alles löschen (mit Bestätigung)\n"
        "/anchors on|off - Abendnachricht (21 Uhr Serverzeit)\n"
        "/report <Problem> - dem Betreiber etwas melden\n\n"
        "Für alles andere: sprich einfach mit mir."
    ),
    'WAITLIST': (
        "Die private Beta ist voll: jeder der %d Plätze verdient echte "
        "Aufmerksamkeit, und ich betreue lieber wenige gut als viele "
        "schlecht. Du stehst auf der Warteliste; dieser Chat bekommt eine "
        "Nachricht, sobald ein Platz frei wird.\n\n"
        "Wenn du gerade jetzt aufhörst und nicht warten kannst: "
        "findahelpline.com listet menschliche Hilfe für dein Land, und das "
        "offene Protokoll, dem ich folge, ist frei lesbar: "
        "github.com/metrox-eth/quit-sponsor."
    ),
    'FALLBACK': (
        "Ich erreiche mein Gehirn gerade nicht: ein technischer Fehler auf "
        "meiner Seite, nicht auf deiner, und nichts von dem, was du "
        "geschrieben hast, ist verloren. Wenn das ein Krisenmoment ist, "
        "warte nicht auf mich: findahelpline.com hat eine menschliche "
        "Leitung für dein Land, und deine lokale Notrufnummer ist rund um "
        "die Uhr erreichbar. Ich bin so schnell wie möglich zurück."
    ),
    'ONB_BUTTONS': [
        [{'text': 'Ich höre jetzt auf', 'callback_data': 'onb:now'}],
        [{'text': 'Schon aufgehört, ich halte durch', 'callback_data': 'onb:holding'}],
        [{'text': 'Ich überlege noch', 'callback_data': 'onb:thinking'}],
    ],
    'ONB_MAP': {
        'onb:now': 'Ich höre jetzt mit dem Rauchen auf. Heute.',
        'onb:holding': 'Ich habe kürzlich aufgehört und halte bisher durch.',
        'onb:thinking': 'Ich überlege noch. Noch nicht entschieden.',
    },
    'DELETE_ASK': 'Das löscht dein Logbuch, dein Profil, alles, wirklich. '
                  'Antworte genau: DELETE',
    'DELETE_DONE': 'Erledigt. Alles gelöscht. Falls du je zurückkommst, '
                   'kostet es ein Wort, und ich fange neu an.',
    'DELETE_CANCEL': 'Löschen abgebrochen. Nichts wurde gelöscht.',
    'REPORT_ACK': 'Notiert und an den Betreiber weitergeleitet. Danke: so '
                  'wird die Beta besser.',
    'ANCHOR': 'Tagesabschluss. Ein Wort genügt: durchgehalten?',
    'EXPORT_EMPTY': 'Dein Logbuch ist noch leer.',
    'EXPORT_CAPTION': 'Dein Logbuch. Ganz deins.',
}

IT = {
    'WELCOME': (
        "Benvenuto. Prima di tutto, le regole oneste del gioco:\n\n"
        "1. Sono uno sponsor IA che segue un protocollo pubblicato e "
        "aperto. Sostegno alla pari, informato dalla ricerca.\n"
        "2. NON sono un medico né un servizio di emergenza. Un sintomo "
        "fisico preoccupante si mostra a un medico; in caso di pericolo o "
        "sofferenza acuta chiama il tuo numero di emergenza locale o "
        "findahelpline.com, non aspettare mai me.\n"
        "3. Solo adulti (18+).\n"
        "4. I tuoi dati: le nostre conversazioni e il tuo diario stanno sul "
        "server dell'operatore. /export ti manda tutto, /delete cancella "
        "tutto, davvero. Le risposte passano per il modello indicato in "
        "/about. Niente pubblicità, niente vendita di dati, niente "
        "addestramento sui tuoi contenuti.\n"
        "5. Testi completi: /terms e /ethics (per ora in inglese).\n\n"
        "Se sei adulto e d'accordo, rispondi: accetto"
    ),
    'CONSENTED': (
        "Fatto, il tuo diario è aperto.\n\n"
        "A che punto sei con il fumo? Un pulsante o le tue parole, vanno "
        "bene entrambi. Un dato: smettere subito, quando la decisione è "
        "tua, regge circa 2,6 volte meglio che fissare una data."
    ),
    'HELP': (
        "/about - modello attuale, privacy, il protocollo\n"
        "/terms - condizioni della beta\n"
        "/ethics - la carta che vincola gli operatori\n"
        "/export - ricevere il tuo diario completo\n"
        "/delete - cancellare tutto (chiede conferma)\n"
        "/anchors on|off - messaggio di fine giornata (21:00 ora server)\n"
        "/report <problema> - segnalare all'operatore\n\n"
        "Per tutto il resto: parlami, semplicemente."
    ),
    'WAITLIST': (
        "La beta privata è piena: ognuno dei %d posti merita attenzione "
        "vera, e preferisco seguire bene pochi che male molti. Sei in lista "
        "d'attesa; questa chat riceverà un messaggio appena si libera un "
        "posto.\n\n"
        "Se stai smettendo adesso e non puoi aspettare: findahelpline.com "
        "elenca supporto umano per il tuo paese, e il protocollo aperto che "
        "seguo è libero: github.com/metrox-eth/quit-sponsor."
    ),
    'FALLBACK': (
        "Non riesco a raggiungere il mio cervello: guasto tecnico mio, non "
        "tuo, e niente di ciò che hai scritto è andato perso. Se questo è "
        "un momento di crisi, non aspettare me: findahelpline.com ha una "
        "linea umana per il tuo paese, e il tuo numero di emergenza locale "
        "risponde a ogni ora. Torno appena possibile."
    ),
    'ONB_BUTTONS': [
        [{'text': 'Smetto adesso', 'callback_data': 'onb:now'}],
        [{'text': 'Ho già smesso, resisto', 'callback_data': 'onb:holding'}],
        [{'text': 'Ci sto ancora pensando', 'callback_data': 'onb:thinking'}],
    ],
    'ONB_MAP': {
        'onb:now': 'Smetto di fumare adesso. Oggi.',
        'onb:holding': 'Ho smesso da poco e per ora resisto.',
        'onb:thinking': 'Ci sto ancora pensando. Non ho deciso.',
    },
    'DELETE_ASK': 'Questo cancella il tuo diario, il tuo profilo, tutto, '
                  'davvero. Rispondi esattamente: DELETE',
    'DELETE_DONE': 'Fatto. Tutto cancellato. Se un giorno torni, costa una '
                   'parola, e ricomincio da zero.',
    'DELETE_CANCEL': 'Cancellazione annullata. Niente è stato cancellato.',
    'REPORT_ACK': "Registrato e inoltrato all'operatore. Grazie: è così "
                  'che la beta migliora.',
    'ANCHOR': 'Chiusura della giornata. Una parola basta: tenuto?',
    'EXPORT_EMPTY': 'Il tuo diario è ancora vuoto.',
    'EXPORT_CAPTION': 'Il tuo diario. Tuo, per intero.',
}

TH = {
    'WELCOME': (
        "ยินดีต้อนรับ กติกาที่ตรงไปตรงมาก่อนเริ่ม:\n\n"
        "1. ผมเป็นพี่เลี้ยง AI ที่ทำงานตามโปรโตคอลแบบเปิดที่เผยแพร่สาธารณะ "
        "เป็นการช่วยเหลือแบบเพื่อนช่วยเพื่อน อิงงานวิจัย\n"
        "2. ผมไม่ใช่หมอ และไม่ใช่บริการฉุกเฉิน อาการทางร่างกายที่น่ากังวลให้ไปพบแพทย์ "
        "หากอยู่ในอันตรายหรือทุกข์ใจรุนแรง โทรเบอร์ฉุกเฉินในพื้นที่ หรือ "
        "findahelpline.com อย่ารอผม\n"
        "3. สำหรับผู้ใหญ่เท่านั้น (18+)\n"
        "4. ข้อมูลของคุณ: บทสนทนาและสมุดบันทึกเก็บบนเซิร์ฟเวอร์ของผู้ดูแล "
        "/export ส่งทั้งหมดให้คุณ /delete ลบทั้งหมดจริง ๆ "
        "คำตอบสร้างโดยโมเดลที่ระบุใน /about ไม่มีโฆษณา ไม่ขายข้อมูล "
        "ไม่เอาเนื้อหาของคุณไปเทรน\n"
        "5. ฉบับเต็ม: /terms และ /ethics (ตอนนี้เป็นภาษาอังกฤษ)\n\n"
        "ถ้าคุณเป็นผู้ใหญ่และยอมรับ ตอบว่า: ยอมรับ"
    ),
    'CONSENTED': (
        "เรียบร้อย สมุดบันทึกของคุณเปิดแล้ว\n\n"
        "ตอนนี้คุณอยู่ตรงไหนกับบุหรี่? กดปุ่มหรือพิมพ์เองก็ได้ "
        "เกร็ดหนึ่ง: การเลิกทันทีเมื่อการตัดสินใจเป็นของคุณเอง "
        "อยู่ได้นานกว่าการนัดวันล่วงหน้าประมาณ 2.6 เท่า"
    ),
    'HELP': (
        "/about - โมเดลปัจจุบัน ความเป็นส่วนตัว โปรโตคอล\n"
        "/terms - เงื่อนไขเบต้า\n"
        "/ethics - กติกาที่ผูกมัดผู้ดูแล\n"
        "/export - รับสมุดบันทึกทั้งหมด\n"
        "/delete - ลบทุกอย่าง (มีขั้นยืนยัน)\n"
        "/anchors on|off - ข้อความปิดท้ายวัน (21:00 เวลาเซิร์ฟเวอร์)\n"
        "/report <ปัญหา> - แจ้งผู้ดูแล\n\n"
        "นอกนั้น: คุยกับผมได้เลย"
    ),
    'WAITLIST': (
        "เบต้าส่วนตัวเต็มแล้ว: ทั้ง %d ที่ต้องได้รับการดูแลจริง ๆ "
        "และผมขอดูแลคนน้อยให้ดี ดีกว่าดูแลคนมากแบบไม่ทั่วถึง "
        "คุณอยู่ในรายชื่อรอแล้ว แชทนี้จะได้รับข้อความทันทีที่มีที่ว่าง\n\n"
        "ถ้าคุณกำลังเลิกอยู่ตอนนี้และรอไม่ได้: findahelpline.com "
        "มีสายด่วนมนุษย์สำหรับประเทศของคุณ และโปรโตคอลที่ผมใช้เปิดให้อ่านฟรีที่ "
        "github.com/metrox-eth/quit-sponsor"
    ),
    'FALLBACK': (
        "ตอนนี้ผมติดต่อสมองตัวเองไม่ได้ เป็นปัญหาทางเทคนิคฝั่งผม ไม่ใช่คุณ "
        "และสิ่งที่คุณเขียนไม่หายไปไหน ถ้าตอนนี้เป็นช่วงวิกฤต อย่ารอผม: "
        "findahelpline.com มีสายด่วนมนุษย์สำหรับประเทศของคุณ "
        "และเบอร์ฉุกเฉินท้องถิ่นรับสายทุกเวลา ผมจะกลับมาเร็วที่สุด"
    ),
    'ONB_BUTTONS': [
        [{'text': 'เลิกเดี๋ยวนี้เลย', 'callback_data': 'onb:now'}],
        [{'text': 'เลิกแล้ว กำลังประคองอยู่', 'callback_data': 'onb:holding'}],
        [{'text': 'ยังคิดอยู่', 'callback_data': 'onb:thinking'}],
    ],
    'ONB_MAP': {
        'onb:now': 'ผมจะเลิกบุหรี่เดี๋ยวนี้ วันนี้เลย',
        'onb:holding': 'เพิ่งเลิกได้ไม่นาน ตอนนี้ยังประคองอยู่',
        'onb:thinking': 'ยังคิดอยู่ ยังไม่ตัดสินใจ',
    },
    'DELETE_ASK': 'นี่จะลบสมุดบันทึก โปรไฟล์ ทุกอย่าง จริง ๆ ตอบให้ตรงว่า: DELETE',
    'DELETE_DONE': 'เสร็จแล้ว ลบทั้งหมดแล้ว ถ้าวันหนึ่งกลับมา แค่คำเดียวก็พอ '
                   'แล้วผมจะเริ่มใหม่ให้',
    'DELETE_CANCEL': 'ยกเลิกการลบ ไม่มีอะไรถูกลบ',
    'REPORT_ACK': 'บันทึกและส่งต่อให้ผู้ดูแลแล้ว ขอบคุณ นี่คือวิธีที่เบต้าพัฒนาขึ้น',
    'ANCHOR': 'ปิดท้ายวัน คำเดียวพอ: รอดไหม?',
    'EXPORT_EMPTY': 'สมุดบันทึกของคุณยังว่างอยู่',
    'EXPORT_CAPTION': 'สมุดบันทึกของคุณ เป็นของคุณทั้งหมด',
}

L10N = {'fr': FR, 'es': ES, 'pt': PT, 'de': DE, 'it': IT, 'th': TH}

CONSENT_WORDS = (
    'agree', 'i agree',
    "j'accepte", 'jaccepte', "d'accord", 'daccord',
    'acepto', 'estoy de acuerdo',
    'concordo', 'aceito',
    'einverstanden', 'ich stimme zu',
    'accetto', 'sono d’accordo',
    'ยอมรับ', 'ตกลง',
)


def lang_of(uid):
    code = str(profile(uid).get('lang', ''))[:2].lower()
    return code if code in L10N else 'en'


def S(uid, key, default):
    pack = L10N.get(lang_of(uid))
    return pack[key] if pack and key in pack else default

WAITLIST = (
    "The private beta is full right now: every one of its %d spots deserves "
    "real attention, and I would rather serve few people well than many "
    "badly. You are on the waiting list; this chat will get a message the "
    "moment a spot opens.\n\n"
    "If you are quitting right now and cannot wait: findahelpline.com lists "
    "human support for your country, and the open protocol I run on is free "
    "to read at github.com/metrox-eth/quit-sponsor."
)


def consented_count():
    if not DATA.exists():
        return 0
    n = 0
    for d in DATA.iterdir():
        f = d / 'profile.json'
        if d.is_dir() and f.exists():
            try:
                if json.loads(f.read_text()).get('consent'):
                    n += 1
            except ValueError:
                pass
    return n


HELP = (
    "/about - current model, privacy mode, the protocol\n"
    "/terms - beta terms of service\n"
    "/ethics - the ethics charter that binds the operators\n"
    "/export - receive your full logbook file\n"
    "/delete - erase everything (asks confirmation)\n"
    "/anchors on|off - evening close message (21:00 server time)\n"
    "/report <what went wrong> - tell the operator something is broken\n\n"
    "Everything else: just talk to me."
)


def about_text():
    return (
        "Model: %s, routed through Virtuals Protocol compute.\n"
        "Honest privacy status (beta): Virtuals publishes no retention policy "
        "for its routing layer, so assume message content is visible to the "
        "route and the model provider. The public launch is gated on a "
        "verified-privacy route (see /terms).\n"
        "Protocol: https://github.com/metrox-eth/quit-sponsor (open source, "
        "including the model fit test this model passed).\n"
        "Operator: metrox (private beta, individual operator).\n"
        "Your data: /export and /delete, both real." % MODEL
    )


IN_FLIGHT = {}  # uid -> (text, started_ts): duplicate-press guard


# ---------- storage ----------

def udir(uid):
    d = DATA / str(uid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def profile(uid):
    f = udir(uid) / 'profile.json'
    if f.exists():
        return json.loads(f.read_text())
    return {}


def save_profile(uid, p):
    (udir(uid) / 'profile.json').write_text(json.dumps(p, indent=1))


def log(uid, role, text, kind='message'):
    entry = {'ts': datetime.now().isoformat(timespec='seconds'),
             'role': role, 'kind': kind, 'text': text}
    with open(udir(uid) / 'logbook.jsonl', 'a') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def recent_messages(uid, n=CONTEXT_TURNS):
    f = udir(uid) / 'logbook.jsonl'
    if not f.exists():
        return []
    lines = f.read_text().splitlines()[-n * 3:]
    out = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get('kind') != 'message':
            continue
        role = 'assistant' if e['role'] == 'sponsor' else 'user'
        out.append({'role': role, 'content': e['text']})
    return out[-n:]


# ---------- telegram ----------

def tg(method, timeout=65, **params):
    req = urllib.request.Request(
        'https://api.telegram.org/bot%s/%s' % (TG_TOKEN, method),
        data=json.dumps(params).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def send(chat_id, text, markup=None):
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)]
    for i, chunk in enumerate(chunks):
        params = {'chat_id': chat_id, 'text': chunk}
        if markup and i == len(chunks) - 1:
            params['reply_markup'] = markup
        tg('sendMessage', **params)


def send_file(chat_id, path, caption=''):
    import mimetypes, uuid
    boundary = uuid.uuid4().hex
    body = b''
    fields = {'chat_id': str(chat_id), 'caption': caption}
    for k, v in fields.items():
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                 % (boundary, k, v)).encode()
    fname = os.path.basename(path)
    ctype = mimetypes.guess_type(fname)[0] or 'application/octet-stream'
    body += ('--%s\r\nContent-Disposition: form-data; name="document"; '
             'filename="%s"\r\nContent-Type: %s\r\n\r\n' % (boundary, fname, ctype)).encode()
    body += Path(path).read_bytes() + b'\r\n'
    body += ('--%s--\r\n' % boundary).encode()
    req = urllib.request.Request(
        'https://api.telegram.org/bot%s/sendDocument' % TG_TOKEN, data=body,
        headers={'Content-Type': 'multipart/form-data; boundary=%s' % boundary})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


# ---------- brain ----------

def system_prompt():
    skill = (SKILL_DIR / 'SKILL.md').read_text()
    safety = (SKILL_DIR / 'SAFETY.md').read_text()
    return ('=== SKILL.md ===\n%s\n\n=== SAFETY.md ===\n%s\n\n%s'
            % (skill, safety, BOT_PREAMBLE))


SYSTEM = system_prompt()


def think(uid, user_text):
    clock = datetime.now().strftime('%A %d %B %Y, %H:%M')
    system = (SYSTEM + '\n\nServer date and time right now: ' + clock +
              ' (use this for any date arithmetic; never guess the date).')
    messages = ([{'role': 'system', 'content': system}]
                + recent_messages(uid)
                + [{'role': 'user', 'content': user_text}])
    payload = json.dumps({'model': MODEL, 'messages': messages,
                          'max_tokens': 1000, 'temperature': 0.7}).encode()
    t0 = time.time()
    for attempt in range(2):
        try:
            req = urllib.request.Request(LLM_URL, data=payload, headers={
                'Authorization': 'Bearer ' + LLM_KEY,
                'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.loads(r.read())
            text = d['choices'][0]['message']['content'].strip()
            if text:
                print('llm ok %.1fs (attempt %d)' % (time.time() - t0, attempt),
                      flush=True)
                return text
        except Exception as e:
            print('llm error (%d, %.1fs): %s' % (attempt, time.time() - t0, e),
                  flush=True)
            time.sleep(2)
    return None


# ---------- handlers ----------

def handle_command(uid, chat, text):
    cmd = text.split()[0].lower().split('@')[0]
    if cmd == '/start':
        send(chat, S(uid, 'WELCOME', WELCOME))
    elif cmd == '/help':
        send(chat, S(uid, 'HELP', HELP))
    elif cmd == '/terms':
        send(chat, (BASE / 'TERMS.md').read_text())
    elif cmd == '/ethics':
        send(chat, (BASE / 'ETHICS.md').read_text())
    elif cmd == '/about':
        send(chat, about_text())
    elif cmd == '/export':
        f = udir(uid) / 'logbook.jsonl'
        if f.exists():
            send_file(chat, str(f),
                      S(uid, 'EXPORT_CAPTION', 'Your logbook. Yours, entirely.'))
        else:
            send(chat, S(uid, 'EXPORT_EMPTY', 'Your logbook is empty so far.'))
    elif cmd == '/delete':
        p = profile(uid)
        p['pending_delete'] = True
        save_profile(uid, p)
        send(chat, S(uid, 'DELETE_ASK',
                     'This erases your logbook, your profile, everything, '
                     'for real. Reply exactly: DELETE'))
    elif cmd == '/report':
        detail = text.partition(' ')[2].strip() or '(no detail given)'
        entry = {'ts': datetime.now().isoformat(timespec='seconds'),
                 'uid': uid, 'report': detail}
        DATA.mkdir(exist_ok=True)
        with open(DATA / '_reports.jsonl', 'a') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        op = SECRETS.get('OPERATOR_CHAT_ID')
        if op:
            try:
                send(int(op), 'REPORT from %s: %s' % (uid, detail))
            except Exception as e:
                print('report forward error: %s' % e, flush=True)
        send(chat, S(uid, 'REPORT_ACK',
                     'Logged and forwarded to the operator. Thank you - '
                     'reports like this are how the beta gets better.'))
    elif cmd == '/anchors':
        p = profile(uid)
        arg = text.split()[1].lower() if len(text.split()) > 1 else ''
        if arg in ('on', 'off'):
            p['anchors'] = (arg == 'on')
            save_profile(uid, p)
            send(chat, 'Evening close is %s.' % arg.upper())
        else:
            send(chat, 'Usage: /anchors on  or  /anchors off')
    else:
        send(chat, "Unknown command. /help lists what exists.")


def handle_message(uid, chat, text):
    p = profile(uid)

    if p.get('pending_delete'):
        if text.strip() == 'DELETE':
            import shutil
            goodbye = S(uid, 'DELETE_DONE',
                        'Done. Everything erased. If you ever come back, '
                        'it costs one word, and I start fresh.')
            shutil.rmtree(udir(uid))
            send(chat, goodbye)
            return
        p.pop('pending_delete', None)
        save_profile(uid, p)
        send(chat, S(uid, 'DELETE_CANCEL', 'Deletion cancelled. Nothing was erased.'))
        return

    if not p.get('consent'):
        if text.strip().lower() in CONSENT_WORDS:
            if consented_count() >= BETA_CAP:
                p['waitlist'] = datetime.now().isoformat(timespec='seconds')
                save_profile(uid, p)
                log(uid, 'system', 'waitlisted (beta full)', kind='event')
                send(chat, S(uid, 'WAITLIST', WAITLIST) % BETA_CAP)
                return
            p['consent'] = datetime.now().isoformat(timespec='seconds')
            p['anchors'] = False
            save_profile(uid, p)
            log(uid, 'system', 'consent given', kind='event')
            pack = L10N.get(lang_of(uid))
            markup = {'inline_keyboard': pack['ONB_BUTTONS']} if pack else ONB_KEYBOARD
            send(chat, S(uid, 'CONSENTED', CONSENTED), markup=markup)
        else:
            send(chat, S(uid, 'WELCOME', WELCOME))
        return

    log(uid, 'user', text)
    try:
        tg('sendChatAction', chat_id=chat, action='typing', timeout=10)
    except Exception:
        pass
    reply = think(uid, text)
    if reply is None:
        send(chat, FALLBACK)
        log(uid, 'system', 'llm failure, fallback sent', kind='event')
        return
    log(uid, 'sponsor', reply)
    send(chat, reply)


def dispatch(uid, chat, text):
    """Per-update worker so a slow LLM call never blocks the poll loop."""
    try:
        if text.startswith('/'):
            handle_command(uid, chat, text)
        else:
            handle_message(uid, chat, text)
    except Exception as e:
        print('handler error %s: %s' % (uid, e), flush=True)
        try:
            send(chat, S(uid, 'FALLBACK', FALLBACK))
        except Exception:
            pass


# ---------- evening anchor ----------

def anchors_loop():
    sent_on = {}
    while True:
        now = datetime.now()
        if now.hour == ANCHOR_HOUR and DATA.exists():
            for d in DATA.iterdir():
                uid = d.name
                if sent_on.get(uid) == str(date.today()):
                    continue
                p = profile(uid)
                if p.get('consent') and p.get('anchors'):
                    try:
                        msg = S(uid, 'ANCHOR', 'Evening close. One word is enough: held?')
                        send(int(uid), msg)
                        log(uid, 'sponsor', msg, kind='anchor')
                        sent_on[uid] = str(date.today())
                    except Exception as e:
                        print('anchor error %s: %s' % (uid, e), flush=True)
        time.sleep(60)


# ---------- main ----------

def main():
    if not TG_TOKEN:
        sys.exit('TELEGRAM_BOT_TOKEN missing in secrets.env')
    DATA.mkdir(exist_ok=True)
    threading.Thread(target=anchors_loop, daemon=True).start()
    print('sponsor bot up, model=%s' % MODEL, flush=True)
    offset_file = DATA / '_offset'
    offset = int(offset_file.read_text()) if offset_file.exists() else 0
    while True:
        try:
            updates = tg('getUpdates', offset=offset, timeout=50)
        except Exception as e:
            print('poll error: %s' % e, flush=True)
            time.sleep(5)
            continue
        if updates.get('result'):
            offset_file.write_text(str(updates['result'][-1]['update_id'] + 1))
        for u in updates.get('result', []):
            offset = u['update_id'] + 1
            cq = u.get('callback_query')
            if cq:
                try:
                    tg('answerCallbackQuery', callback_query_id=cq['id'])
                except Exception as e:
                    print('answerCallback error (non-fatal): %s' % e, flush=True)
                uid = (cq.get('from') or {}).get('id')
                chat = ((cq.get('message') or {}).get('chat') or {}).get('id')
                pack = L10N.get(lang_of(uid)) if uid else None
                onb = pack['ONB_MAP'] if pack else ONB_MAP
                phrase = onb.get(cq.get('data', ''))
                if phrase and uid and chat:
                    threading.Thread(target=dispatch,
                                     args=(uid, chat, phrase), daemon=True).start()
                continue
            msg = u.get('message') or {}
            text = msg.get('text')
            chat = (msg.get('chat') or {}).get('id')
            uid = (msg.get('from') or {}).get('id')
            if not (text and chat and uid):
                continue
            lc = (msg.get('from') or {}).get('language_code', '')
            if lc:
                p = profile(uid)
                if p.get('lang') != lc:
                    p['lang'] = lc
                    save_profile(uid, p)
            threading.Thread(target=dispatch,
                             args=(uid, chat, text), daemon=True).start()


# ---------- offline selftest ----------

def selftest():
    """Dry-run of the state machine with send() stubbed. No network."""
    global send, think
    sent = []
    send = lambda chat, text, markup=None: sent.append(text)
    think = lambda uid, text: '[sponsor reply to: %s]' % text
    uid, chat = 999001, 999001

    import shutil
    if udir(uid).exists():
        shutil.rmtree(udir(uid))

    handle_command(uid, chat, '/start')
    assert 'reply: agree' in sent[-1]
    handle_message(uid, chat, 'hello?')
    assert 'reply: agree' in sent[-1], 'gate must hold before consent'
    handle_message(uid, chat, 'agree')
    assert 'logbook is open' in sent[-1]
    assert profile(uid).get('consent'), 'consent must be stored'
    handle_message(uid, chat, 'I want to quit smoking')
    assert sent[-1].startswith('[sponsor reply'), 'post-consent goes to model'
    msgs = recent_messages(uid)
    assert msgs[-2]['role'] == 'user' and msgs[-1]['role'] == 'assistant'
    handle_command(uid, chat, '/anchors on')
    assert profile(uid)['anchors'] is True
    handle_command(uid, chat, '/delete')
    handle_message(uid, chat, 'no wait')
    assert 'cancelled' in sent[-1]
    assert udir(uid).exists()
    handle_command(uid, chat, '/delete')
    handle_message(uid, chat, 'DELETE')
    assert not (DATA / str(uid)).exists(), 'delete must be real'
    print('selftest OK (%d messages)' % len(sent))


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        main()

"""Read what the operator meant, not only what they typed.

tidy(message, ...) returns the message with stray characters removed ("disr][uptions"), common shorthand spelt out
("wich", "r", "pls"), words close to the vocabulary of this product corrected ("shipmnts", "roterdam", "critcal"),
and shipment numbers written loosely ("s1007", "shipment 1005", a bare "1002") turned into their ids. Everything
that reads a chat message runs it through here first, so a slip of the keyboard is not taken for an off-topic
question. A word is only changed to a word of the vocabulary that starts with the same letter and is very close to
it; ordinary words are left alone, and nothing is added that was not typed.
"""
import difflib
import re

SHORTHAND = {"r": "are", "u": "you", "ur": "your", "pls": "please", "plz": "please", "thx": "thanks", "ty": "thanks", "abt": "about",
             "wat": "what", "wht": "what", "wot": "what", "whats": "what is", "wats": "what is", "hw": "how", "hows": "how is",
             "wher": "where", "wich": "which", "whch": "which", "wen": "when", "y": "why", "hlep": "help", "halp": "help", "b4": "before",
             "tmrw": "tomorrow", "tmr": "tomorrow", "tomoz": "tomorrow", "asap": "asap", "nxt": "next", "msg": "message", "info": "information",
             "shpmnt": "shipment", "shpmnts": "shipments", "goin": "going", "doin": "doing", "evrything": "everything", "evrythng": "everything",
             "evry": "every", "aroun": "around", "arnd": "around", "nr": "near", "frm": "from", "wk": "week", "cant": "cannot", "im": "i am"}
VOCAB = """shipment shipments fleet route routes reroute reschedule port ports airport warehouse depot delay delays delayed late cost costs price
rate rates risk risks disruption disruptions strike strikes closure closures closed storm weather warning congestion arrive arriving arrival depart
departing leave leaving cargo pallet pallets container containers reefer reefers trailer trailers tonnes carrier carriers freight deliver delivery
penalty demurrage surcharge source sources evidence customs ferry truck trucks ship ships vessel plane planes flight stock inventory dispatch orders
corridor plan planned options option approve critical severe watch clear urgent attention priority priorities summary overview status exposure total
optimise optimize everything cheapest safest check search scan happening anything wrong where which what when help urgent today tomorrow friday monday
tuesday wednesday thursday saturday sunday deadline level levels affected trouble worst expensive waiting wait""".split()
_KEEP = set("""the a an and or of to in on at by for from with is are was be it this that these those all any some my our your me i we you do does did
can could will would should have has had not no yes how many much more most less about around near into over out up down new old now then than one two
three there here they them their its if but so as go going show tell give get make need want know see look list find""".split())


def _closest(word: str, vocab: list[str]) -> str | None:
    if len(word) < 4:
        return None
    best = difflib.get_close_matches(word, [v for v in vocab if v[0] == word[0] and abs(len(v) - len(word)) <= 2], n=1, cutoff=0.78 if len(word) >= 6 else 0.8)
    if not best:
        return None
    if len(word) <= 5 and len(best[0]) == len(word) and sorted(best[0]) != sorted(word):
        return None  # a short word with one letter different is usually another real word ("shock" is not "stock")
    return best[0]


def tidy(message: str, places: set[str] = frozenset(), ids: set[str] = frozenset(), extra: set[str] = frozenset()) -> str:
    """The message as it was meant. `places`, `extra`: lower-case words to treat as vocabulary (place and carrier
    names); `ids`: the shipment ids that exist, so a loose number is only turned into an id that is real."""
    text = re.sub(r"[^\w\s\-?.,:;'/€>&()+]", "", message or "")          # "disr][uptions" -> "disruptions"
    text = re.sub(r"(?<=\w)[\[\]{}|\\^~`_*#<=]+(?=\w)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    by_number = {i.split("-")[-1]: i for i in ids}

    def loose_id(m):
        return by_number.get(m.group(1), m.group(0))
    text = re.sub(r"\b(?:s|shipment|shipmnt|load)[\s\-#]*(\d{3,5})\b", loose_id, text, flags=re.I)   # s1007, shipment 1005
    if len(re.findall(r"(?<![\w\-])\d+", text)) == 1 and not re.search(r"eur|€|euro|budget|cost|under|below|within|pallet|container|reefer|trailer|tonne|\bkm\b|\bkg\b", text, re.I):
        text = re.sub(r"(?<![\w\-.:,€])(\d{4})(?![\w.:,])", loose_id, text)                           # a bare 1002, when it can only be a shipment
    vocab = sorted(set(VOCAB) | set(places) | set(extra))
    known = set(vocab) | _KEEP

    def fix(m):
        word = m.group(0)
        low = word.lower()
        if low in SHORTHAND:
            return SHORTHAND[low]
        if low in known or any(ch.isdigit() for ch in low) or word.upper() in ids:
            return word
        return _closest(low, vocab) or word
    return re.sub(r"[A-Za-z][A-Za-z']*", fix, text)

import requests
from bs4 import BeautifulSoup
import sys
import shelve
import random
import os
import json
from holelist import HoleList
import re

auto_add_word_lists = []

def display_auto_add_info(ctx):
    if not auto_add_word_lists: return
    print("[info] new words will be automatically added to: ", end="")
    names = [ctx.word_list_names[n_idx] for n_idx in auto_add_word_lists]
    print(", ".join(names))

BASE_URL = "https://jisho.org/search/"
SEARCH_DEPTH = 10
EDITOR = "nvim"
DB_FILE = "flashcards"
WORDS_FILE = "words.json"

def clear():
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")

def split_and_strip(s, at):
    words = [e.strip() for e in s.split(at)]
    return list(filter(None, words))

PUNCTUATION = (0x3000, 0x303F)
HIRAGANA = (0x3040, 0x309F)
KATAKANA = (0x30A0, 0x30FF)
KATAKANA_PHONETIC = (0x31F0, 0x31FF)
KANA = [PUNCTUATION, HIRAGANA, KATAKANA, KATAKANA_PHONETIC]

def is_kana(char):
    code = ord(char)
    for uni_range in KANA:
        if uni_range[0] <= code and code <= uni_range[1]:
            return True
    return False

LATIN_THRESHOLD = 0x036F

def filter_kanji(s):
    kanjis = []
    for char in s:
        if ord(char) > LATIN_THRESHOLD:
            kanjis.append(char)
    return kanjis

def prompt(other=None):
    while True:
        choice = input("([y]es/[n]o): ").strip().lower()
        if choice == 'y' or choice == "yes" or choice == "はい": 
            return True
        elif choice == 'n' or choice == "no" or choice == "いええ":
            return False
        for option in other:
            if choice in option:
                return option[0]

def choose_options(lst, msg="Choose options", empty_is_first=True, output=True):
    n = len(lst)
    choices = set()
    if output:
        print(msg, end=" ")
        if empty_is_first:
            print("(empty means first):")
        else:
            print("")
        for i in range(n):
            print(f"{i+1}. {lst[i]}")
    while True:
        resp = input("Select: ").strip().lower()
        if resp == 'b' or resp == "back":
            return None
        if not resp:
            return lst[:1] if empty_is_first else []
        resp = split_and_strip(resp, ",")
        for s in resp:
            if s.isdigit():
                i = int(s) - 1
                if 0 <= i and i < n:
                    choices.add(i)
                    last = i
                else:
                    print(f"Error: no such option {i+1}")
                    break
            elif '-' in s:
                r = split_and_strip(s, '-')
                if len(r) != 2 or not r[0].isdigit() or not r[1].isdigit():
                    print(f"Error: invalid range {s}")
                f, t = int(r[0]), int(r[1])
                for i in range(f-1, t):
                    choices.add(i)
            else:
                print("Error: option must be a number")
                break
        else:
            break
        continue
    return [lst[i] for i in range(len(lst)) if i in choices]

def display_selected(word):
    clear()
    if not word:
        print("Nothing selected")
    else:
        word.display("Selected @")

JOYO = 0
GRADE = 1
HIGH = 7
LEVEL = 8
OTHER = 13

NUM_RESERVED_WORD_LISTS = 5

class Context:
    def init_empty(self):
        self.kanjis = []
        self.kanji_idx_by_symbol = {}
        self.words = HoleList()
        self.word_idx_by_symbols = {}
        self.word_lists = {"jlpt n" + str(i): set() for i in range(1, 6)}
        self.word_list_names = HoleList(["jlpt n" + str(i) for i in range(1, 6)])
        self.single_kanji_word_lists = tuple([set() for _ in range(14)])
        self.slots = tuple([set() for _ in range(6)])
        self.invalid = set()
        self.no_single_kanji_word_cache = set()
        self.correct = []
        self.incorrect = []
        self.stash = []

    def write_to_file(self, path):
        with shelve.open(path) as db:
            db["context"] = self

    def read_from_file(self, path):
        with shelve.open(path) as db:
            ctx = db["context"]
            self.kanjis = ctx.kanjis
            self.kanji_idx_by_symbol = ctx.kanji_idx_by_symbol
            self.words = ctx.words
            self.word_idx_by_symbols = ctx.word_idx_by_symbols
            self.word_lists = ctx.word_lists
            self.word_list_names = ctx.word_list_names
            self.single_kanji_word_lists = ctx.single_kanji_word_lists
            self.slots = ctx.slots
            self.invalid = ctx.invalid
            self.no_single_kanji_word_cache = ctx.no_single_kanji_word_cache
            self.correct = ctx.correct
            self.incorrect = ctx.incorrect
            self.stash = ctx.stash

class Kanji:
    def __init__(self, char, meanings, categories, parts, radical):
        self.char = char
        self.meanings = meanings
        self.categories = categories
        self.parts = parts
        self.radical = radical

    def scrape_radical_helper(radical, trim_stack, ctx):
        k_idx = ctx.kanji_idx_by_symbol.get(radical)
        if k_idx is None:
            k_idx = Kanji.scrape(radical, trim_stack, ctx)
        if k_idx == -1:
            ctx.kanji_idx_by_symbol[radical] = -1
            return -1
        return k_idx

    def trim_parts(trim_stack, ctx):
        while trim_stack:
            k_idx = trim_stack.pop()
            k = ctx.kanjis[k_idx]
            parts = k.parts
            trimmed = parts.copy()
            for k_idx_o in parts:
                for k_idx_i in parts:
                    k_i = ctx.kanjis[k_idx_i]
                    if k_idx_o in k_i.parts:
                        trimmed.remove(k_idx_o)
                        break
            k.parts = trimmed

    # this does not prevent duplicates
    def scrape(char, trim_stack, ctx):
        print(f"Adding kanji {char}")
        response = requests.get(BASE_URL + char + "%23kanji")
        if response.status_code != 200:
            print(f"Error: could not get data for kanji {char}")
            return -1
        parsed = BeautifulSoup(response.text, "html.parser")
        if not parsed.body.find("div", attrs={"class": "kanji details"}):
            print(f"Error: {char} is not a valid kanji")
            return -1
        meanings = parsed.body.find("div", attrs={"class": "kanji-details__main-meanings"}).text
        meanings = split_and_strip(meanings, ",")
        #meanings = choose_options(meanings, "Choose meanings")
        category = False
        categories = set()
        grade = parsed.body.find("div", attrs={"class": "grade"})
        if grade and not grade.text.isspace():
            words = split_and_strip(grade.text, " ")
            if words[0] == "Jōyō":
                categories.add(JOYO)
                category = True
            if words[-1].isdigit():
                categories.add(GRADE + int(words[-1]) - 1)
                category = True
            elif words[-1] == "high":
                categories.add(HIGH)
                category = True
        jlpt = parsed.body.find("div", attrs={"class": "jlpt"})
        if jlpt:
            categories.add(LEVEL + int(jlpt.text.strip()[-1]) - 1)
            category = True
        if not category:
            categories.add(OTHER)
        radical_info = parsed.body.find_all("div", attrs={"class": "radicals"})
        radicals = list(map(BeautifulSoup.get_text, radical_info[1].find_all("a")))
        idx = len(ctx.kanjis)
        ctx.kanjis.append(Kanji(char, None, None, None, None))
        ctx.kanji_idx_by_symbol[char] = idx
        trim_stack.append(idx)
        parts = []
        for radical in radicals:
            if radical == char:
                continue
            k_idx = Kanji.scrape_radical_helper(radical, trim_stack, ctx)
            if k_idx != -1:
                parts.append(k_idx)
        radicals = filter_kanji(radical_info[0].text)
        for k_idx in parts:
            k = ctx.kanjis[k_idx]
            if k.char in radicals:
                radical = k_idx
                break
        else:
            radical = re.sub("\(.*\)", "", radical_info[0].text).strip()[-1]
            if radical != char:
                radical = Kanji.scrape_radical_helper(radical, trim_stack, ctx)
            else:
                radical = idx
        k = Kanji(char, meanings, categories, parts, radical)
        ctx.kanjis[idx] = k
        return idx

    def display_with_meaning(self, radical):
        meanings = ", ".join(self.meanings)
        is_radical = " (radical)" if self.char == radical else ""
        print(f"{self.char}{is_radical}: {meanings}")

    def display_categories(self):
        cat_names = []
        for c in self.categories:
            if c == JOYO:
                cat_names.insert(0, "jōyō kanji")
            elif c >= GRADE and c < GRADE + 6:
                cat_names.insert(1, f"taught in grade {c-GRADE+1}")
            elif c == HIGH:
                cat_names.insert(1, f"taught in junior high")
            elif c >= LEVEL and c < LEVEL + 5:
                cat_names.insert(2, f"jlpt n{c-LEVEL+1}")
        print(", ".join(cat_names))

    def display_parts(self, ctx):
        r = ctx.kanjis[self.radical]
        radical = r.char
        if self.radical not in self.parts and radical != self.char:
            r.display_with_meaning(radical)
        for k_idx in self.parts:
            k = ctx.kanjis[k_idx]
            k.display_with_meaning(radical)

class Word:
    # does not prevent duplicates
    def __init__(self, word, furigana, meanings=None, kanji_index=None, word_lists=None):
        self.word = word
        self.furigana = furigana
        self.meanings = meanings if meanings else []
        self.kanji_index = kanji_index if kanji_index else []
        self.word_lists = word_lists if word_lists else set()
        self.slot = 0
        self.upper = ""
        self.lower = ""
        furi_idx = 0
        diff = 0
        i = 0
        while i < len(word):
            char = word[i]
            if not is_kana(char):
                if furi_idx < len(self.furigana):
                    self.lower += ' ' * diff * 2 + char
                    furi = self.furigana[furi_idx]
                    self.upper += furi
                    diff = len(furi) - 1
                    furi_idx += 1
                else:
                    self.lower += char
                    if diff > 0:
                        diff -= 1
            else:
                if diff > 0:
                    self.lower += ' ' * diff * 2
                diff = 0
                self.lower += char
                self.upper += ' ' * 2
            i += 1
        if diff > 0:
            self.lower += ' ' * diff * 2

    def calculate_kanji_positions(word):
        kanji_positions = []
        for i in range(len(word)):
            char = word[i]
            if not is_kana(char):
                kanji_positions.append(i)
        return kanji_positions

    def scrape(word, ctx, exact_match=True, single_kanji=False, data=None):
        w_data = None
        if data:
            w_data = data.get(word)
            if not w_data:
                data = None
        if not w_data:
            response = requests.get(BASE_URL + word)
            if response.status_code != 200:
                print(f"Error: could not get data for word {word}")
                return -1
            parsed = BeautifulSoup(response.text, "html.parser")
            results = parsed.body.find_all("div", attrs={"class": "concept_light clearfix"}) 
            if not results:
                print(f"Error: invalid word {word}")
                return -1
            if parsed.body.find("div", attrs={"id": "no-matches"}):
                print(f"Error: no matches for word {word}")
                return -1
            for i in range(min(SEARCH_DEPTH, len(results))):
                result = results[i]
                text_container = result.find("span", attrs={"class": "text"})
                if text_container:
                    text = text_container.text.strip()
                else:
                    continue
                kanji_positions = Word.calculate_kanji_positions(text)
                if single_kanji and len(kanji_positions) != 1:
                    continue
                if not exact_match or text == word:
                    break
            else:
                if exact_match:
                    print(f"Error: could not find exact match for {word}")
                    print("Do you want to input it manually?")
                    if prompt():
                        return add_word_manual(word, ctx)
                    return -1
                elif single_kanji:
                    print(f"Error: could not find single kanji word for {word}")
                    ctx.no_single_kanji_word_cache.add(word[0])
                    return -1
            if not exact_match and text != word:
                k_idx = ctx.word_idx_by_symbols.get(text)
                if (k_idx is not None) or (data and data.get(text)):
                    return -1
            furigana = result.find("span", attrs={"class": "furigana"})
            singles = furigana.find("rt")
            if singles:
                furigana = [singles.text]
            else:
                furigana = list(filter(lambda s: not s.isspace() and s,
                    map(BeautifulSoup.get_text, furigana)))
            word = text
        else:
            kanji_positions = Word.calculate_kanji_positions(word)
            furigana = w_data["furigana"]
        w = Word(word, furigana)
        w.display("Adding @")
#       if exact_match:
#           w.display("Adding @")
#       else:
#           w.display("Do you want to add @? ")
#           if (not prompt()):
#               return -1
        if not w_data:
            meanings = result.find_all("span", attrs={"class": "meaning-meaning"})
            meanings = split_and_strip(";".join(map(BeautifulSoup.get_text, meanings)), ";")
            w.meanings = choose_options(meanings, "Choose meanings")
            if w.meanings is None:
                return -1
        else:
            w.meanings = w_data["meanings"]
        for i in kanji_positions:
            char = word[i]
            if not is_kana(char):
                k_idx = ctx.kanji_idx_by_symbol.get(char)
                if k_idx is None: 
                    trim_stack = []
                    k_idx = Kanji.scrape(char, trim_stack, ctx)
                    Kanji.trim_parts(trim_stack, ctx)
                    if k_idx == -1:
                        return -1
                w.kanji_index.append(k_idx)
        idx = ctx.words.add(w)
        ctx.word_idx_by_symbols[word] = idx
        if w_data and "slot" in w_data:
            slot = w_data["slot"]
            w.slot = slot
        else:
            slot = 0
        ctx.slots[slot].add(idx)
        if not w_data:
            jlpt = result.find("span", attrs={"class": "concept_light-tag label"})
        else:
            jlpt = w_data["level"]
        if jlpt:
            if not w_data:
                jlpt = jlpt.text.strip()
            if "JLPT" in jlpt:
                level = jlpt[-1]
                ctx.word_lists["jlpt n" + level].add(idx)
                w.word_lists.add(int(level) - 1)
        for n_idx in auto_add_word_lists:
            w.word_lists.add(n_idx)
            name = ctx.word_list_names[n_idx]
            ctx.word_lists[name].add(idx)
        if len(w.kanji_index) == 1:
            k = ctx.kanjis[w.kanji_index[0]]
            for c in k.categories:
                ctx.single_kanji_word_lists[c].add(idx)
        else:
            for i in w.kanji_index:
                k = ctx.kanjis[i]
                m = (-1, sys.maxsize)
                for c in k.categories:
                    l = len(ctx.single_kanji_word_lists[c])
                    if l < m[1]:
                        m = (c, l)
                for y in ctx.single_kanji_word_lists[m[0]]:
                    if i == ctx.words[y].kanji_index[0]:
                        break
                else:
                    k_char = ctx.kanjis[i].char
                    if k_char not in ctx.no_single_kanji_word_cache:
                        Word.scrape(
                                k_char,
                                ctx,
                                exact_match=False,
                                single_kanji=True,
                                data=data)
        return idx

    def display(self, surrounding="@"):
        pos = surrounding.find('@')
        if self.upper and not self.upper.isspace():
            print(' ' * pos + self.upper)
        print(surrounding.replace('@', self.lower))

    def display_word_lists(self, ctx):
        wl_names = []
        for l in self.word_lists:
            wl_names.insert(l, ctx.word_list_names[l])
        print(", ".join(wl_names))

    def display_full(self, ctx):
        self.display()
        print("Meaning:")
        for meaning in self.meanings:
            print(f"• {meaning}")
        is_single = len(self.kanji_index) == 1
        if len(self.kanji_index) != 0:
            radical = ctx.kanjis[self.kanji_index[0]].radical
            radical = ctx.kanjis[radical].char if is_single else None
            print("Kanji:")
            for k_idx in self.kanji_index:
                k = ctx.kanjis[k_idx]
                k.display_with_meaning(radical)
        if is_single:
            k = ctx.kanjis[self.kanji_index[0]]
            if k.parts:
                print("Parts:")
                k.display_parts(ctx)
            if OTHER not in k.categories:
                print("Categories: ", end="")
                k.display_categories()
        if len(self.word_lists) != 0:
            print("Word lists: ", end="")
            self.display_word_lists(ctx)


def json_to_word_data(j, ctx):
    w_data = {}
    furigana = list(map(str.strip, filter(lambda s: not s.isspace() and s, j["furigana"])))
    w_data["furigana"] = furigana
    meanings = list(map(str.strip, filter(lambda s: not s.isspace() and s, j["meanings"])))
    if not meanings:
        print("Error: meanings field is empty")
        return None
    w_data["meanings"] = meanings
    level = j["jlpt n"]
    if level < 0 or 5 < level:
        print(f"Error: invalid jlpt level {level}")
        return None
    w_data["level"] = "JLPT n" + str(level) if level != 0 else ""
    return w_data

TEMPLATE = {
        "furigana": [""],
        "meanings": [""],
        "jlpt n": 0
        }

def add_word_manual(word, ctx):
    f = open("tmp.json", "w+")
    json.dump(TEMPLATE, f, indent=4)
    f.close()
    while True:
        os.system(f"{EDITOR} tmp.json")
        f = open("tmp.json", "r")
        s = str(f.read())
        f.close()
        j = json.loads(s)
        w_data = json_to_word_data(j, ctx)
        if not w_data:
            print("Do you want to adjust the data?")
            if prompt():
                continue
            return -1
        break
    data = {word: w_data}
    return Word.scrape(word, ctx, data=data)

def add_words(ctx):
    manual = False
    sel = None
    idx = -1
    clear()
    while True:
        display_auto_add_info(ctx)
        word = input("Add: ").strip().lower()
        if word == 'b' or word == "back":
            break
        if word == 'e' or word == "edit":
            if sel:
                edit_words(ctx, sel=sel, idx=idx)
            clear()
            continue
        if word == 'm' or word == "manual":
            if manual:
                print("Switching from manual to auto")
            else:
                print("Switching from auto to manual")
            manual = not manual
            continue
        w_idx = ctx.word_idx_by_symbols.get(word)
        if w_idx is not None:
            w = ctx.words[w_idx]
            w.display("Already added @")
            continue
        clear()
        idx = Word.scrape(word, ctx) if not manual else add_word_manual(word, ctx)
        sel = ctx.words[idx] if idx != -1 else None

def parse_edit_cmd(cmd, lst):
    cmd = split_and_strip(cmd, " ")
    if len(cmd) != 2:
        print("Error: invalid command format")
        return None
    action, n = (cmd[0], cmd[1]) if cmd[1].isdigit() else (cmd[1], cmd[0])
    if (not n.isdigit()) or (int(n) - 1 not in range(len(lst))):
        print(f"Error: {n} is not a valid index")
        return None
    n = int(n) - 1
    return action, n

def edit_word_lists(ctx):
    updated = True
    while True:
        if updated:
            clear()
            print("Edit word lists:")
            names = list(ctx.word_list_names)[NUM_RESERVED_WORD_LISTS:]
            i = 0
            for name in names:
                n_idx = ctx.word_list_names.index(name)
                auto = "[auto]" if n_idx in auto_add_word_lists else ""
                print(f"{i+1}. {name} {auto}")
                i += 1
            updated = False
        cmd = input("Command: ").strip().lower()
        if not cmd:
            continue
        if cmd == 'b' or cmd == "back":
            return
        if cmd == 'a' or cmd == "add":
            name = input("Add word list: ").strip()
            if name in ctx.word_lists:
                print(f"Error: word list {name} already exists")
                continue
            ctx.word_list_names.add(name)
            ctx.word_lists[name] = set()
            updated = True
            continue
        parsed = parse_edit_cmd(cmd, names)
        if not parsed:
            continue
        action, n = parsed
        name = names[n]
        n_idx = ctx.word_list_names.index(name)
        if action == 'r' or action == "rename":
            new_name = input(f"{name} -> ").strip()
            if new_name in ctx.word_lists:
                print("Error: name collision with word list {new_name}")
                continue
            ctx.word_list_names[n_idx] = new_name
            ctx.word_lists[new_name] = ctx.word_lists.pop(name)
        elif action == 'd' or action == "delete":
            print(f"Are you sure, that you want to delete word list {name}?")
            if not prompt():
                continue
            for w_idx in ctx.word_lists[name]:
                w = ctx.words[w_idx]
                w.word_lists.discard(n_idx)
            del ctx.word_lists[name]
            del ctx.word_list_names[n_idx]
        elif action == "auto":
            if n_idx in auto_add_word_lists:
                auto_add_word_lists.remove(n_idx)
            else:
                auto_add_word_lists.append(n_idx)
        updated = True

def choose_word_lists_wrapper(names):
    choices = choose_options(
            names,
            msg="Choose word lists:",
            empty_is_first=False)
    while True:
        if choices is None:
            return None
        if choices:
            break
        choices = choose_options(names, output=False, empty_is_first=False)
    return choices

def add_to_word_lists(word, w_idx, ctx):
    names = list(ctx.word_list_names)[NUM_RESERVED_WORD_LISTS:]
    minus = list(map(lambda i: ctx.word_list_names[i], word.word_lists))
    names = list(filter(lambda n: n not in minus, names))
    display_selected(word)
    while True:
        if not names:
            print(f"{word.word} is member of all user generated word lists")
            return -1
        choices = choose_word_lists_wrapper(names)
        if not choices:
            return
        display_selected(word)
        for name in choices:
            n_idx = ctx.word_list_names.index(name)
            print(f"Adding {word.word} to word list {name}")
            word.word_lists.add(n_idx)
            ctx.word_lists[name].add(w_idx)
            names.remove(name)

def remove_from_word_lists(word, w_idx, ctx):
    names = list(ctx.word_list_names)[NUM_RESERVED_WORD_LISTS:]
    display_selected(word)
    while True:
        if not names:
            print(f"{word.word} is not in any user generated word list")
            return -1
        choices = choose_word_lists_wrapper(names)
        if not choices:
            return
        display_selected(word)
        for name in choices:
            n_idx = ctx.word_list_names.index(name)
            print(f"Removing {word.word} from word list {name}")
            word.word_lists.discard(n_idx)
            ctx.word_lists[name].discard(w_idx)
            names.remove(name)

def edit_meaning(word):
    updated = True
    while True:
        if updated:
            display_selected(word)
            for i in range(len(word.meanings)):
                print(f"{i+1}. {word.meanings[i]}")
            updated = False
        cmd = input("Command: ").strip().lower()
        if cmd == 'b' or cmd == "back":
            return
        if cmd == 'a' or cmd == "add":
            meaning = input("Add meaning: ").strip()
            word.meanings.append(meaning)
            updated = True
            continue
        parsed = parse_edit_cmd(cmd, word.meanings)
        if not parsed:
            continue
        action, n = parsed
        if action == 'c' or action == "change":
            meaning = input(f"{word.meanings[n]} -> ").strip()
            word.meanings[n] = meaning
        elif action == 'd' or action == "delete":
            if len(word.meanings) == 1:
                print("Error: cannot delete last meaning of word")
                continue
            del word.meanings[n]
        else:
            print(f"Error: unknown command {action}")
            continue
        updated = True

def edit_words(ctx, sel=None, idx=-1):
    display_selected(sel)
    while True:
        word = input("Edit: ").strip().lower()
        if not word:
            continue
        if word == 'b' or word == "back":
            break
        elif word == 'd' or word == "delete":
            if not sel:
                continue
            print("Are you sure?")
            if not prompt():
                continue
            ctx.invalid.add(idx)
            word_lists = sel.word_lists
            for i in word_lists:
                l = ctx.word_lists[ctx.word_list_names[i]]
                l.discard(idx)
            if len(sel.kanji_index) == 1:
                k_idx = sel.kanji_index[0]
                single_kanji_word_lists = ctx.kanjis[k_idx].categories
                for i in single_kanji_word_lists:
                    l = ctx.single_kanji_word_lists[i]
                    l.discard(idx)
            l = ctx.slots[sel.slot]
            l.discard(idx)
            del ctx.words[idx]
            del ctx.word_idx_by_symbols[sel.word]
            sel = None
        elif word == 'm' or word == "meaning":
            if not sel:
                continue
            edit_meaning(sel)
        elif word == 'i' or word == "info":
            if not sel:
                continue
            display_selected(sel)
            sel.display_full(ctx)
            continue
        elif word == 'a' or word == "add":
            if not sel:
                continue
            if add_to_word_lists(sel, idx, ctx) == -1:
                continue
        elif word == 'r' or word == "remove":
            if not sel:
                continue
            if remove_from_word_lists(sel, idx, ctx) == -1:
                continue
        else:
            w_idx = ctx.word_idx_by_symbols.get(word)
            if w_idx is not None:
                sel = ctx.words[w_idx]
                idx = w_idx
            else:
                print(f"Could not find {word}")
                continue
        display_selected(sel)

def enumerate_all_word_lists(ctx):
    all_word_list_names = []
    for i in range(len(ctx.slots)):
        n = len(ctx.slots[i])
        wl_name = f"slot {i+1}"
        all_word_list_names.append(wl_name)
        print(f"{i+1}. {wl_name}: {n}")
    print("\nWord lists:")
    i = len(ctx.slots)
    for wl_name in ctx.word_list_names:
        n = len(ctx.word_lists[wl_name])
        i += 1
        all_word_list_names.append(wl_name)
        print(f"{i}. {wl_name}: {n}")
    i += 1
    n = len(ctx.words)
    wl_name = "all"
    all_word_list_names.append(wl_name)
    print(f"{i}. {wl_name}: {n}")
    print("\nSingle kanji word lists:")
    i += 1
    n = len(ctx.single_kanji_word_lists[JOYO])
    wl_name = "jōyō kanji"
    all_word_list_names.append(wl_name)
    print(f"{i}. {wl_name}: {n}")
    for y in range(6):
        n = len(ctx.single_kanji_word_lists[GRADE+y])
        i += 1
        wl_name = f"grade {y+1}"
        all_word_list_names.append(wl_name)
        print(f"{i}. {wl_name}: {n}")
    i += 1
    n = len(ctx.single_kanji_word_lists[HIGH])
    wl_name = "junior high"
    all_word_list_names.append(wl_name)
    print(f"{i}. {wl_name}: {n}")
    for y in range(5):
        n = len(ctx.single_kanji_word_lists[LEVEL+y])
        i += 1
        wl_name = f"jlpt n{y+1}" 
        all_word_list_names.append(wl_name)
        print(f"{i}. {wl_name}: {n}")
    i += 1
    n = len(ctx.single_kanji_word_lists[OTHER])
    wl_name = "other"
    all_word_list_names.append(wl_name)
    print(f"{i}. {wl_name}: {n}")
    return all_word_list_names

def select_word_lists(all_word_list_names, ctx):
    word_lists = []
    names = []
    options = tuple(range(1, len(all_word_list_names)+1))
    choices = choose_options(options, output=False, empty_is_first=False)
    word_list_names = list(ctx.word_list_names)
    if not choices:
        return choices
    for idx in choices:
        idx -= 1
        names.append(all_word_list_names[idx])
        n = len(ctx.slots)
        if idx < n:
            word_lists.append(ctx.slots[idx])
            continue
        idx -= n
        n = len(word_list_names)
        if idx < n:
            word_lists.append(ctx.word_lists[word_list_names[idx]])
            continue
        idx -= n
        if idx == 0:
            word_lists.append(set(ctx.word_idx_by_symbols.values()))
            continue
        idx -= 1
        if idx == 0:
            word_lists.append(ctx.single_kanji_word_lists[JOYO])
            continue
        idx -= 1
        if idx < 6:
            word_lists.append(ctx.single_kanji_word_lists[GRADE+idx])
            continue
        idx -= 6
        if idx == 0:
            word_lists.append(ctx.single_kanji_word_lists[HIGH])
            continue
        idx -= 1
        if idx < 5:
            word_lists.append(ctx.single_kanji_word_lists[LEVEL+idx])
            continue
        idx -= 5
        if idx == 0:
            word_lists.append(ctx.single_kanji_word_lists[OTHER])
            continue
        print("Fatal error: reached unreachable code")
    if names:
        print("Selected", ", ".join(names))
    return word_lists

def select_words(ctx):
    clear()
    all_word_list_names = enumerate_all_word_lists(ctx)
    words = set()
    while True:
        word_lists = select_word_lists(all_word_list_names, ctx)
        if word_lists is None:
            return None
        if word_lists == []:
            if not words:
                print("Error: can't review empty word list")
                continue
            break
        word_list = set.union(*word_lists)
        word_list.difference_update(words)
        if not word_list:
            print("Error: can't select from empty word list")
            continue
        n = 0
        while True:
            n = input("Number of cards: ").strip()
            if not n.isdigit():
                print(f"Error: invalid number {n}")
                continue
            n = min(int(n), len(word_list))
            break
        words.update(random.sample(tuple(word_list), n))
    return words

def review_words(ctx):
    incorrect = ctx.incorrect
    if not incorrect:
        ctx.invalid.clear()
        word_list = select_words(ctx)
        if not word_list:
            return
        incorrect = [[w_idx, 0] for w_idx in word_list]
    correct = ctx.correct
    stash = ctx.stash
    abort = False
    while True:
        while incorrect or stash:
            if not incorrect:
                incorrect = stash
                stash = []
            clear()
            c_idx = random.randrange(len(incorrect))
            card = incorrect[c_idx]
            w_idx = card[0]
            if w_idx in ctx.invalid:
                del incorrect[c_idx]
                ctx.invalid.discard(w_idx)
                continue
            w = ctx.words[w_idx]
            print(w.word)
            usr = input("[Check] ").strip().lower()
            if usr == 'b' or usr == "back":
                ctx.correct = correct
                ctx.incorrect = incorrect
                ctx.stash = stash
                return
            elif usr == 'a' or usr == "abort":
                abort = True
                break
            del incorrect[c_idx]
            err = 0
            while True:
                if not err: clear()
                else: print()
                err = 0
                w.display_full(ctx)
                print("Were you able to answer?")
                cmd = prompt([("e", "edit"), ("a", "add"), ("r", "remove")])
                if cmd == "e":
                    edit_words(ctx, sel=w, idx=w_idx)
                    if w_idx in ctx.invalid:
                        ctx.invalid.discard(w_idx)
                        break
                elif cmd == "a":
                    err = add_to_word_lists(w, w_idx, ctx)
                elif cmd == "r":
                    err = remove_from_word_lists(w, w_idx, ctx)
                elif cmd:
                    correct.append(card)
                    break
                else:
                    card[1] += 1
                    stash.append(card)
                    break
        if abort:
            break
        print("Repeat with same deck?")
        if not prompt():
            break
        incorrect, correct = correct, incorrect
    if not abort:
        for card in correct:
            wrong = card[1]
            if wrong == 1:
                continue
            w_idx = card[0]
            w = ctx.words[w_idx]
            #if wrong >= 2:
            #    if w.slot > 0:
            #        ctx.slots[w.slot].discard(w_idx)
            #        w.slot = max(w.slot - wrong + 1, 0)
            #        ctx.slots[w.slot].add(w_idx)
            #elif w.slot < len(ctx.slots) - 1:
            #    ctx.slots[w.slot].discard(w_idx)
            #    w.slot += 1
            #    ctx.slots[w.slot].add(w_idx)
            if wrong > 0:
                if w.slot > 0:
                    ctx.slots[w.slot].discard(w_idx)
                    w.slot = 0
                    ctx.slots[0].add(w_idx)
            elif w.slot < len(ctx.slots) - 1:
                ctx.slots[w.slot].discard(w_idx)
                w.slot += 1
                ctx.slots[w.slot].add(w_idx)
    ctx.invalid.clear()
    ctx.correct = []
    ctx.incorrect = []
    ctx.stash = []

def export_words(ctx):
    data = {}
    for w in ctx.words:
        w_data = {}
        w_data["furigana"] = w.furigana
        w_data["meanings"] = w.meanings
        level = list(filter(lambda l: l < NUM_RESERVED_WORD_LISTS, w.word_lists))
        level = level[0] + 1 if level else 0
        w_data["level"] = "JLPT n" + str(level) if level else ""
        w_data["slot"] = w.slot
        data[w.word] = w_data
    with open(WORDS_FILE, "w+") as f:
        json.dump(data, f)

def import_words(ctx):
    try:
        with open(WORDS_FILE, "r") as f:
            data = json.load(f)
    except:
        print("Error: could not open {WORDS_FILE}")
    for word, w_data in data.items():
        w_idx = ctx.word_idx_by_symbols.get(word)
        if w_idx is not None:
            print(f"Already added {word} -> skipping")
            continue
        Word.scrape(word, ctx, data=data)

def main():
    clear()
    ctx = Context()
    try: 
        ctx.read_from_file(DB_FILE)
    except Exception as e: 
        print(f"Warning: could not read from {DB_FILE}.db")
        print("Warning: if you don't want to lose everything when exiting, kill the program")
        ctx.init_empty()
    abort = False
    while True:
        display_auto_add_info(ctx)
        choice = input("Action: ").strip().lower()
        if choice == 'a' or choice == "add":
            add_words(ctx)
        elif choice == 'l' or choice == "list":
            edit_word_lists(ctx)
        elif choice == 'e' or choice == "edit":
            edit_words(ctx)
        elif choice == 'r' or choice == "review":
            review_words(ctx)
        elif choice == "exit":
            break
        elif choice == "abort":
            abort = True
            break
        elif choice == "write":
            clear()
            print("Saving changes...")
            ctx.write_to_file(DB_FILE)
            continue
        elif choice == "export":
            clear()
            print(f"Exporting words to file {WORDS_FILE}...")
            export_words(ctx)
            continue
        elif choice == "import":
            clear()
            print(f"Importing words from {WORDS_FILE}...")
            import_words(ctx)
            continue
        else:
            print(f"Error: invalid action {choice}")
            continue
        clear()
    if not abort:
        ctx.write_to_file(DB_FILE)
    
if __name__ == "__main__":
    main()

This program was created because anki would not compile for me on OpenBSD.
If somebody for whatever reason decides to try this, be aware that this was programmed in 3 days and only provides bare minimum functionality.

Features (not in anki):
- automatic scraping of meaning, furigana and word lists from jisho.org
- kanji meanings for every kanji in word are shown when flipped
- for every new kanji in word, a single kanji word will be added with this particular kanji
- easy creation and management of word lists 
- will probably scale very badly because python

How to get japanese input to work on OpenBSD (this worked for me):
- install japanese fonts
- install fcitx, fcitx-anthy, fcitx-configtool-qt and kasumi
- put this into .xsession:
    ```export XMODIFIERS=@im=fcitx
    export GTK_IM_MODULE=fcitx
    export QT_IM_MODULE=fcitx
    ...
    exec dbus-launch i3```
- autostart fcitx5 (I put it in i3config):
    ```exec --no-startup-id fcitx5 -rd```
- configure with configtool to use anthy

Actions:
- [a]dd
- [l]ist: manage word lists
- [e]dit
- [r]eview
- write: save changes
- exit: exit and save
- abort: exit without saving

Add:
- input the word to add and follow prompts
- [e]dit: the current word is automatically selected
- [m]anual: switch to manual mode and back
    - edit the EDITOR variable in flashcard.py to your favorite text editor
    - you will get a json form to fill out
    - example furigana input for 三月(month): ["さん", "がつ"]

Edit:
- input word to select it
- [d]elete: delete selected word
- [m]eaning: edit meaning
- [i]nfo: display word info
- [a]dd: add to word lists
- [r]emove: remove from word lists

Edit meaning:
- [c]hange {index}
- [d]elete {index}
- [a]dd

Manage word lists:
- [r]ename {index}
- [d]elete {index}
- [a]dd

Review:
- choose word lists and from their union select n cards
- repeat until no word list is chosen
- review process will start:
    - if you get a card wrong once, card stays in the same slot
    - if you get a card wrong twice, card goes back one slot
    - otherwise card advances one slot
- [b]ack: cancel and save state
- [a]bort: cancel without saving
- cards that are loaded from save which have been deleted in the meanwhile are discarded

Notes:
- almost all prompts allow you to input [b]ack which will cancel the action and go back
- everywhere where you can choose several options you can provide comma separated list and range notation is supported (e.g. 1,4-6,9)

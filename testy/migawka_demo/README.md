Migawka danych demo sprzed resetu do próby generalnej (tag `przed-proba`): karty klientów, wyniki analiz, prośby produktowe,
propozycje, materiały i transkrypcje. Testy offline, które sprawdzały „prawdziwe dane”, czytają je stąd, bo `reset_demo.py` czyści
żywe repozytorium. Dane fikcyjne (demo). Katalog jest poza ścieżką `ops/transkrypcje/**`, więc nie uruchamia workflow.

`wyniki_proba/` to wyniki analizy z próby generalnej (15.10): ten sam materiał (transkrypcje), ale model nazwał sprawy inaczej niż w `wyniki/`.
Testy kotwic w cytatach sprawdzają, że oczekiwania rozwiązują się w obu wersjach.

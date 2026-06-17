# Makefile — build paper.pdf via pdflatex + bibtex.

TEX     := pdflatex
BIB     := bibtex
MAIN    := main
SECTIONS := $(wildcard sections/*.tex)
FIGS    := $(wildcard figures/*)
TABLES  := $(wildcard tables/*)

.PHONY: all clean watch

all: $(MAIN).pdf

$(MAIN).pdf: $(MAIN).tex $(SECTIONS) references.bib $(FIGS) $(TABLES)
	$(TEX)  -interaction=nonstopmode $(MAIN).tex
	-$(BIB) $(MAIN)
	$(TEX)  -interaction=nonstopmode $(MAIN).tex
	$(TEX)  -interaction=nonstopmode $(MAIN).tex

clean:
	rm -f $(MAIN).aux $(MAIN).bbl $(MAIN).blg $(MAIN).log $(MAIN).out $(MAIN).toc
	rm -f sections/*.aux
	rm -f $(MAIN).pdf

watch:
	@command -v latexmk >/dev/null 2>&1 || { echo "latexmk required"; exit 1; }
	latexmk -pdf -pvc -interaction=nonstopmode $(MAIN).tex

# Makefile — build paper.pdf via pdflatex + bibtex.
# Falls back to TeX Live in Docker when pdflatex is not on PATH.

TEX     := pdflatex
BIB     := bibtex
MAIN    := main
SECTIONS := $(wildcard sections/*.tex)
FIGS    := $(wildcard figures/*)
TABLES  := $(wildcard tables/*)
DOCKER  := docker run --rm -v "$(CURDIR):/workdir" -w /workdir texlive/texlive:latest

.PHONY: all clean watch docker

all: $(MAIN).pdf

$(MAIN).pdf: $(MAIN).tex $(SECTIONS) references.bib $(FIGS) $(TABLES)
	@command -v $(TEX) >/dev/null 2>&1 || { $(MAKE) docker; exit 0; }
	$(TEX)  -interaction=nonstopmode $(MAIN).tex
	-$(BIB) $(MAIN)
	$(TEX)  -interaction=nonstopmode $(MAIN).tex
	$(TEX)  -interaction=nonstopmode $(MAIN).tex

docker:
	$(DOCKER) sh -c '$(TEX) -interaction=nonstopmode $(MAIN).tex && $(BIB) $(MAIN) && $(TEX) -interaction=nonstopmode $(MAIN).tex && $(TEX) -interaction=nonstopmode $(MAIN).tex'

clean:
	rm -f $(MAIN).aux $(MAIN).bbl $(MAIN).blg $(MAIN).log $(MAIN).out $(MAIN).toc
	rm -f sections/*.aux
	rm -f $(MAIN).pdf

watch:
	@command -v latexmk >/dev/null 2>&1 || { echo "latexmk required"; exit 1; }
	latexmk -pdf -pvc -interaction=nonstopmode $(MAIN).tex

all: fxs jinja2-templates
.PHONY: all

# Include standard NCS examples build definitions and rules
include $(NCS_DIR)/src/ncs/build/include.ncs.mk

SRC = $(wildcard yang/*.yang)
DIRS = ../load-dir java/src/$(JDIR)/$(NS)
FXS = $(SRC:yang/%.yang=../load-dir/%.fxs)

### Uncomment below if using YANG submodules
### Note: the 'SRC =' line above will need to be altered to explicitly list yang
### top-level modules and _not_ submodules
# YANGPATH += yang

### Yang package dependencies
YANGPATH += ../../common/src/yang
YANGPATH += ../../pdp/src/yang
# YANGPATH += ../../smn-common/src/yang


### Yang NED dependencies
# YANGPATH += ../../<ned-name>/src/ncsc-out/modules/yang \

# XML compiled from Jinja2
CONFIG_XML_J2 = $(wildcard ../templates/*.xml.j2)
CONFIG_XML_OUT = $(CONFIG_XML_J2:.xml.j2=.xml)
JINJA2_CLI_VENV = /tmp/jinja2-cli
JINJA2_CLI = $(JINJA2_CLI_VENV)/bin/jinja2


NCSCPATH   = $(YANGPATH:%=--yangpath %)
YANGERPATH = $(YANGPATH:%=--path %)

fxs: $(DIRS) $(FXS)

$(DIRS):
	mkdir -p $@

../load-dir/%.fxs: yang/%.yang
	$(NCSC)  `ls $*-ann.yang  > /dev/null 2>&1 && echo "-a $*-ann.yang"` \
             $(NCSCPATH) -c -o $@ $<

$(JINJA2_CLI):
	python -m venv $(JINJA2_CLI_VENV)
	$(JINJA2_CLI_VENV)/bin/pip install jinja2-cli

jinja2-templates: $(JINJA2_CLI) $(CONFIG_XML_OUT)

../templates/%.xml: ../templates/%.xml.j2
	$(JINJA2_CLI) $< | xmlstarlet format > $@

clean:
	rm -rf $(DIRS) $(CONFIG_XML_OUT)
.PHONY: clean jinja2-install jinja2-templates



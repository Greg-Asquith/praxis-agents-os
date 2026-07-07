SHELL := /bin/sh
.DEFAULT_GOAL := help

include makefiles/config.mk
include makefiles/help.mk
include makefiles/local.mk
include makefiles/deployment.mk
include makefiles/checks.mk

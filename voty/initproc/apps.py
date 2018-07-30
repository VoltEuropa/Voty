# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initproc App
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

from django.apps import AppConfig

# --------------------------- Initproc Config ----------------------------------
class InitprocConfig(AppConfig):

  # XXX does this make initproc models importable?
  name = "voty.initproc"
  verbose_name = "Initiative Process"



"""Qt services without widgets: printing, background workers, the print-queue controller.

core/ and generator/ never import Qt; everything that needs QThread / QPrinter lives here.
"""

"""
SlapPyEngine — Hello World

Opens an 800×600 window that clears to a dark slate colour.
Close the window to exit.
"""
import pharos_engine as se

engine = se.Engine()   # loads defaults from config/engine.yml
engine.run()

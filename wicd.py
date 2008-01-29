#!/usr/bin/env python

""" wicd - wireless connection daemon frontend implementation

This module implements a usermode frontend for wicd.  It updates connection
information, provides an (optional) tray icon, and allows for launching of 
the wicd GUI and Wired Profile Chooser.

class TrayIcon() -- Parent class of TrayIconGUI and IconConnectionInfo.
    class TrayConnectionInfo() -- Child class of TrayIcon which provides
        and updates connection status.
    class TrayIconGUI() -- Child class of TrayIcon which implements the tray.
        icon itself.  Parent class of StatusTrayIconGUI and EggTrayIconGUI.
    class StatusTrayIconGUI() -- Implements the tray icon using a 
                                 gtk.StatusIcon.
    class EggTrayIconGUI() -- Implements the tray icon using egg.trayicon.
def usage() -- Prints usage information.
def main() -- Runs the wicd frontend main loop.

"""

#
#   Copyright (C) 2007 Adam Blackburn
#   Copyright (C) 2007 Dan O'Reilly
#
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License Version 2 as
#   published by the Free Software Foundation.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import sys
import gtk
import gobject
import dbus
import dbus.service
import getopt
import time

# Wicd specific imports
import wpath
import misc
import gui

# Import egg.trayicon if we're using an older gtk version
if not (gtk.gtk_version[0] >= 2 and gtk.gtk_version[1] >= 10):
    import egg.trayicon
    USE_EGG = True
else:
    USE_EGG = False
    
if getattr(dbus, 'version', (0, 0, 0)) >= (0, 41, 0):
    import dbus.glib

if sys.platform == 'linux2':
    # Set process name.  Only works on Linux >= 2.1.57.
    try:
        import dl
        libc = dl.open('/lib/libc.so.6')
        libc.call('prctl', 15, 'wicd\0', 0, 0, 0) # 15 is PR_SET_NAME
    except Exception:
        print 'Failed to rename wicd process'
        pass

if __name__ == '__main__':
    wpath.chdir(__file__)
    
log = misc.LogWriter()
bus = dbus.SystemBus()

# Connect to the daemon
try:
    print 'Attempting to connect tray to daemon...'
    proxy_obj = bus.get_object('org.wicd.daemon', '/org/wicd/daemon')
    print 'Success.'
except Exception:
    print 'Can\'t connect to the daemon, trying to start it automatically...'
    misc.PromptToStartDaemon()
    time.sleep(1)
    try:
        print 'Attempting to connect tray to daemon...'
        proxy_obj = bus.get_object('org.wicd.daemon', '/org/wicd/daemon')
        print 'Success.'
    except:
        print 'Failed to start daemon.  Aborting.'
        sys.exit(1)

daemon = dbus.Interface(proxy_obj, 'org.wicd.daemon')
wireless = dbus.Interface(proxy_obj, 'org.wicd.daemon.wireless')
wired = dbus.Interface(proxy_obj, 'org.wicd.daemon.wired')
config = dbus.Interface(proxy_obj, 'org.wicd.daemon.config')
                    
_ = misc.get_gettext()
language = {}
language['connected_to_wireless'] = _('Connected to $A at $B (IP: $C)')
language['connected_to_wired'] = _('Connected to wired network (IP: $A)')
language['not_connected'] = _('Not connected')
language['killswitch_enabled'] = _('Wireless Kill Switch Enabled')
language['connecting'] = _('Connecting')
language['wired'] = _('Wired Network')

class TrayIcon():
    """Base Tray Icon class
    
    Base Class for implementing a tray icon to display network status.
    
    """
    def __init__(self, use_tray):
        if USE_EGG:
            self.tr = self.EggTrayIconGUI(use_tray)
        else:
            self.tr = self.StatusTrayIconGUI(use_tray)
        self.icon_info = self.TrayConnectionInfo(self.tr, use_tray)
        

    class TrayConnectionInfo():
        """Class for updating the tray icon status"""
        def __init__(self, tr, use_tray=True):
            """Initialize variables needed for the icon status methods."""
            self.last_strength = -2
            self.still_wired = False
            self.network = ''
            self.tried_reconnect = False
            self.connection_lost_counter = 0
            self.tr = tr
            self.use_tray = use_tray
            self.update_tray_icon()

        def wired_profile_chooser(self):
            """Launch the wired profile chooser."""
            gui.WiredProfileChooser()
            daemon.SetNeedWiredProfileChooser(False)

        def update_tray_icon(self, state=None, info=None):
            """Updates the tray icon and current connection status"""
            if self.use_tray == False: return False

            if not state or not info:
                [state, info] = daemon.GetConnectionStatus()
            
            if state == misc.WIRED:
                wired_ip = info[0]
                self.tr.set_from_file(wpath.images + "wired.png")
                self.tr.set_tooltip(language['connected_to_wired'].replace('$A',
                                                                     wired_ip))

            elif state == misc.WIRELESS:
                lock = ''
                wireless_ip = info[0]
                self.network = info[1]
                strength = info[2]
                cur_net_id = int(info[3])
                sig_string = daemon.FormatSignalForPrinting(str(strength))
                
                if wireless.GetWirelessProperty(cur_net_id, "encryption"):
                    lock = "-lock"
                    
                self.tr.set_tooltip(language['connected_to_wireless']
                                    .replace('$A', self.network)
                                    .replace('$B', sig_string)
                                    .replace('$C', str(wireless_ip)))
                self.set_signal_image(strength, lock)
                
            elif state == misc.CONNECTING:
                if info[0] == 'wired' and len(info) == 1:
                    cur_network = language['wired']
                else:
                    cur_network = info[1]
                self.tr.set_tooltip(language['connecting'] + " to " + 
                                    cur_network + "...")
                self.tr.set_from_file(wpath.images + "no-signal.png")
                
            elif state == misc.NOT_CONNECTED:
                self.tr.set_from_file(wpath.images + "no-signal.png")
                if wireless.GetKillSwitchEnabled():
                    status = (language['not_connected'] + " (" + 
                             language['killswitch_enabled'] + ")")
                else:
                    status = language['not_connected']
                self.tr.set_tooltip(status)
            else:
                print 'Invalid state returned!!!'
                return False

            return True

        def set_signal_image(self, wireless_signal, lock):
            """Sets the tray icon image for an active wireless connection"""
            if daemon.GetSignalDisplayType() == 0:
                if wireless_signal > 75:
                    signal_img = "high-signal"
                elif wireless_signal > 50:
                    signal_img = "good-signal"
                elif wireless_signal > 25:
                    signal_img = "low-signal"
                else:
                    signal_img = "bad-signal"
            else:
                if wireless_signal >= -60:
                    signal_img = "high-signal"
                elif wireless_signal >= -70:
                    signal_img = "good-signal"
                elif wireless_signal >= -80:
                    signal_img = "low-signal"
                else:
                    signal_img = "bad-signal"

            img_file = (wpath.images + signal_img + lock + ".png")
            self.tr.set_from_file(img_file)


    class TrayIconGUI():
        """Base Tray Icon class
        
        Implements methods and variables used by both egg/StatusIcon
        tray icons.

        """
        def __init__(self, use_tray):
            menu = """
                    <ui>
                    <menubar name="Menubar">
                    <menu action="Menu">
                    <menuitem action="Connect"/>
                    <separator/>
                    <menuitem action="About"/>
                    <menuitem action="Quit"/>
                    </menu>
                    </menubar>
                    </ui>
            """
            actions = [
                    ('Menu',  None, 'Menu'),
                    ('Connect', gtk.STOCK_CONNECT, '_Connect...', None,
                     'Connect to network', self.on_preferences),
                    ('About', gtk.STOCK_ABOUT, '_About...', None,
                     'About wicd-tray-icon', self.on_about),
                    ('Quit',gtk.STOCK_QUIT,'_Quit',None,'Quit wicd-tray-icon',
                     self.on_quit),
                    ]
            actg = gtk.ActionGroup('Actions')
            actg.add_actions(actions)
            self.manager = gtk.UIManager()
            self.manager.insert_action_group(actg, 0)
            self.manager.add_ui_from_string(menu)
            self.menu = (self.manager.get_widget('/Menubar/Menu/About').
                                                                  props.parent)
            self.gui_win = None
            self.current_icon_path = None
            self.use_tray = use_tray

        def on_activate(self, data=None):
            """Opens the wicd GUI"""
            self.toggle_wicd_gui()

        def on_quit(self, widget=None):
            """Closes the tray icon"""
            sys.exit(0)

        def on_preferences(self, data=None):
            """Opens the wicd GUI """
            self.toggle_wicd_gui()

        def on_about(self, data = None):
            """Opens the About Dialog"""
            dialog = gtk.AboutDialog()
            dialog.set_name('wicd tray icon')
            dialog.set_version('1.0')
            dialog.set_comments('An icon that shows your network connectivity')
            dialog.set_website('http://wicd.sourceforge.net')
            dialog.run()
            dialog.destroy()

        def toggle_wicd_gui(self):
            """Toggles the wicd GUI"""
            if self.gui_win == None:
                self.gui_win = gui.appGui()
            elif self.gui_win.is_visible == False:
                self.gui_win.show_win()
            else:
                self.gui_win.exit()
                return True
        

    class EggTrayIconGUI(TrayIconGUI):
        """Tray Icon for gtk < 2.10
        
        Uses the deprecated egg.trayicon module to implement the tray icon.
        
        """
        def __init__(self, use_tray=True):
            """Initializes the tray icon"""
            TrayIcon.TrayIconGUI.__init__(self, use_tray)
            self.use_tray = use_tray
            if not use_tray: 
                self.toggle_wicd_gui()
                return

            self.tooltip = gtk.Tooltips()
            self.eb = gtk.EventBox()
            self.tray = egg.trayicon.TrayIcon("WicdTrayIcon")
            self.pic = gtk.Image()
            self.tooltip.set_tip(self.eb, "Initializing wicd...")
            self.pic.set_from_file("images/no-signal.png")

            self.eb.connect('button_press_event', self.tray_clicked)
            self.eb.add(self.pic)
            self.tray.add(self.eb)
            self.tray.show_all()

        def tray_clicked(self, widget, event):
            """Handles tray mouse click events"""
            if event.button == 1:
                self.toggle_wicd_gui()
            if event.button == 3:
                self.menu.popup(None, None, None, event.button, event.time)

        def set_from_file(self, val=None):
            """Calls set_from_file on the gtk.Image for the tray icon"""
            if not self.use_tray: return
            self.pic.set_from_file(val)

        def set_tooltip(self, val):
            """
            
            Sets the tooltip for the gtk.ToolTips associated with this
            tray icon.

            """
            if not self.use_tray: return
            self.tooltip.set_tip(self.eb, val)


    class StatusTrayIconGUI(gtk.StatusIcon, TrayIconGUI):
        """Class for creating the wicd tray icon on gtk > 2.10
        
        Uses gtk.StatusIcon to implement a tray icon.
        
        """
        def __init__(self, use_tray=True):
            TrayIcon.TrayIconGUI.__init__(self, use_tray)
            self.use_tray = use_tray
            if not use_tray: 
                self.toggle_wicd_gui()
                return

            gtk.StatusIcon.__init__(self)

            self.current_icon_path = ''
            daemon.SetForcedDisconnect(False)
            self.set_visible(True)
            self.connect('activate', self.on_activate)
            self.connect('popup-menu', self.on_popup_menu)
            self.set_from_file(wpath.images + "no-signal.png")
            self.set_tooltip("Initializing wicd...")

        def on_popup_menu(self, status, button, timestamp):
            """Opens the right click menu for the tray icon"""
            self.menu.popup(None, None, None, button, timestamp)

        def set_from_file(self, path = None):
            """Sets a new tray icon picture"""
            if not self.use_tray: return
            if path != self.current_icon_path:
                self.current_icon_path = path
                gtk.StatusIcon.set_from_file(self, path)


def usage():
    """Print usage information."""
    print """
wicd 1.40
wireless (and wired) connection daemon front-end.

Arguments:
\t-n\t--no-tray\tRun wicd without the tray icon.
\t-h\t--help\t\tPrint this help information.
"""

def main(argv):
    """ The main frontend program.

    Keyword arguments:
    argv -- The arguments passed to the script.

    """
    print 'Loading...'
    use_tray = True

    try:
        opts, args = getopt.getopt(sys.argv[1:], 'nh', ['help', 'no-tray'])
    except getopt.GetoptError:
        # Print help information and exit
        usage()
        sys.exit(2)

    for opt, a in opts:
        if opt in ('-h', '--help'):
            usage()
            sys.exit()
        elif opt in ('-n', '--no-tray'):
            use_tray = False

    # Set up the tray icon GUI and backend
    tray_icon = TrayIcon(use_tray)

    # Check to see if wired profile chooser was called before icon
    # was launched (typically happens on startup or daemon restart).
    if daemon.GetNeedWiredProfileChooser():
        daemon.SetNeedWiredProfileChooser(False)
        tray_icon.icon_info.wired_profile_chooser()

    bus.add_signal_receiver(tray_icon.icon_info.wired_profile_chooser,
                            'LaunchChooser', 'org.wicd.daemon')

    bus.add_signal_receiver(tray_icon.icon_info.update_tray_icon,
                            'StatusChanged', 'org.wicd.daemon')
    print 'Done.'
    
    mainloop = gobject.MainLoop()
    mainloop.run()


if __name__ == '__main__':
    main(sys.argv)

# irc class to connect to irc servers
# written by isivisi

import thread
from pybotextra import * 
import socket
import time
import re
import sys
import os
import commandController
from commandController import *
import json
import random
import urllib # py3 import urllib.request

PWD = os.getcwd()

class chatters:
    def __init__(self, user, con):
        self.api = "http://tmi.twitch.tv/group/user/{user}/chatters"
        self.user = user
        self.con = con
        self.check_time = 15
        self.chatterCount = 0
        self.mods = []
        self.viewers = []
        self.failures = 0						# count all the failed attempts at getting info
        self.failureMax = 10

        thread.start_new_thread(self.loopChatter, ())

    def getChatterInfo(self):
        url = self.api.replace("{user}", self.user)
        response = urllib.urlopen(url)
        data = json.loads(response.read())
        return data

    def loopChatter(self):
        while 1:
            try:
                time.sleep(self.check_time)

                chatInfo = self.getChatterInfo()
                #printHTML("%s" % (chatInfo,))
                self.chatterCount = chatInfo["chatter_count"]
                self.mods = chatInfo["chatters"]["moderators"]
                self.viewers = chatInfo["chatters"]["viewers"]

                for user in self.mods:
                    self.con.addMode(user, "+o")
                self.failures = 0 # reset
            except:
                self.failures += 1
                if (self.failures >= self.failureMax):
                    pybotPrint("[CHATTERS] Have not received any updates in a while.", "filter")
                    self.failures = 0


# irc object
class irc:
    def __init__(self, server, port, channel, nick, password, hook, filters, db):
        self.server = server
        self.port = port
        self.channel = channel
        self.user = self.channel.replace("#", '')
        self.nick = nick
        self.hook = hook
        self.connected = False
        self.socket = ""
        self.ping_timeout = 0
        self.ping_timeout_max = 300
        self.chat_timeout_max = 60 										# minutes
        self.chat_check_mods = 30										# seconds
        self.chat_time = 0												# auto incremented dont change
        self.password = password
        self.totalUsers = 0
        self.users = {}
        self.filterDb = {}  											# if filters need persistent data. list of all created dictionaries
        self.cmdc = cmdControl(self, db, self.channel)
        self.linkgrabber = False
        self.linkbanned = []
        self.botIsMod = False
        self.closed = False
        self.chatters = chatters(self.user, self)
        self.mysql = db

        self.filters = []
        for i in filters:
            self.filters.append(i+".py")

        filterList = ""
        for f in self.filters:
            filterList += "%s " % f.upper()
        if (filterList != ""): pybotPrint("[PYBOT] %s filters loaded" % filterList)


        pybotPrint("[PYBOT] IRC object initialized, starting ping check...")
        thread.start_new_thread(self.ping, ())
        #thread.start_new_thread(self.getMods, ())
        thread.start_new_thread(self.checkMod, ()) # waits to see if mod
        thread.start_new_thread(self.chatTimeoutCheck, ())
        thread.start_new_thread(self.getLinkBanned, ())

    def chatTimeoutCheck(self):
        time.sleep(60)
        self.chat_time += 1
        if (self.chat_time == self.chat_timeout_max):
            self.msg("There has not been any activity for the past %s minutes, pybot is now disconnecting from your chat." % self.chat_timeout_max)
            self.close()
        else:
            self.chatTimeoutCheck()

    def filter(self, user, data):
        for i in self.filters:
            thread.start_new_thread(self._filterUser, (user, data, i))

    def _filterUser(self, user, data, filter):
        sys.argv = [user, data]
        execfile(PWD+"//filters//"+filter)

    def checkMod(self):
        time.sleep(120);
        pybotPrint("[PYBOT] checking mod status...")
        pybotPrint("%s" % self.botIsMod)
        if not (self.botIsMod):
            self.msg("Pybot is not a mod and will not function properly.")

    def getCmdControl(self):
        return self.cmdController

    # so filters can access persistent data
    def accessFileDb(self, name):
        try:
            dataFile = open(PWD + "//db//%s" % name, "r")
        except:
            dataFile = open(PWD + "//db//%s" % name, "w")
            #dataFile.write("0\n")
            dataFile.close()
            dataFile = open(PWD + "//db//%s" % name, "r")

        return dataFile

    def accessDb(self, name):
        try:
            return self.filterDb[name]
        except:
            self.filterDb[name] = {}										# setup dictionary
            return self.filterDb[name]

    def kick(self, name):
        self.msg(".timeout %s" % name)
        pybotPrint("[PYBOT] Kicked user %s" % name)

    def ban(self, name):
        self.msg(".ban %s" % name)
        pybotPrint("[PYBOT] Banned user %s" % name)

    def connect(self):
        self.socket = ""
        self.socket = socket.socket()
        self.socket.connect((self.server, self.port))
        pybotPrint("[PYBOT] Sending user info...")
        self.socket.send("USER %s\r\n" % self.nick)
        self.socket.send("PASS %s\r\n" % self.password)
        self.socket.send("NICK %s\r\n" % self.nick)
        self.socket.send("TWITCHCLIENT 3\r\n")
        #self.socket.send("CAP REQ :twitch.tv/membership") #request membership but disables chat for some reason

        if self.check_login_status(self.socket.recv(1024)):
            pybotPrint("[PYBOT] login success")
            self.msg("Pybot has connected to your chat.")
        else:
            pybotPrint("[PYBOT] login failed")
            self.retry()

        pybotPrint("[PYBOT] Joining channel " + self.channel)
        self.joinchannel(self.channel)

        self.connected = True
        self.ping_timeout = self.ping_timeout_max
        self.closed = False

        self.getLoop()

    def getMods(self):
        while 1:
            time.sleep(self.chat_check_mods)
        #self.msg("/mods", False)

    def joinchannel(self, channel):
        self.socket.send("JOIN %s\r\n" % channel)
        self.socket.send("WHOIS %s" % self.nick)

    def check_login_status(self, data):
        if re.match(r'^:(testserver\.local|tmi\.twitch\.tv) NOTICE \* :Login unsuccessful\r\n$', data):
            return False
        else:
            return True

    def retry(self):
        self.close(True)
        pybotPrint("Retrying connection in 15 seconds...")
        time.sleep(15)
        self.connect()

    def msg(self, text, show=True):
        if self.connected == True:
            self.socket.send("PRIVMSG %s :%s\r\n" % (self.channel, text))
            if (show): pybotPrint(self.nick + " : " + text, "usermsg")

    def privmsg(self, user, text):
        if self.connected == True:
            self.socket.send("PRIVMSG %s :%s\r\n" % (user, text))

    def rawmsg(self, text):
        if self.connected == True:
            self.socket.send(text+"\r\n")

    def get(self):
        try:
            msg = self.socket.recv(2048)
            msg = msg.strip("\n\r")
            return msg
        except:
            return "ERROR"

    def getSetting(self, setting):
        value = self.mysql.query_r("SELECT %s FROM user WHERE userName = '%s'" % (setting, self.user))
        if (value[0][0] == "1"): return True
        else: return False

    def getLoop(self):
        try:
            while self.connected == True:
                messageFull = self.get()
                messageList = messageFull.split('\r\n')

                #print messageFull
                #twitchnotify :  1 viewer resubscribed while you were away!

                for msg in messageList:
                    ev = ""

                    if msg == "ERROR":
                        ev = "server_lost"
                        self.close()

                    elif not "PRIVMSG" in msg:

                        if "Nickname is already in use" in msg:
                            ev = "nick_taken"

                        if "Cannot send to channel" in msg:
                            ev = "server_cantchannel"

                        if "QUIT" in msg:
                            ev = "user_quit"
                            name = self.getPrivMsgName(msg)
                            pybotPrint("%s has left the channel" % name, "irc")

                        if "JOIN" in msg:
                            if not self.nick in msg:
                                ev = "user_join"
                                name = self.getPrivMsgName(msg)
                                self.totalUsers += 1
                                pybotPrint("[IRC] %s has joined the channel (%s)" % (name, self.totalUsers), "irc")

                        if "PART" in msg:
                            if not self.nick in msg:
                                ev = "user_part"
                                name = self.getPrivMsgName(msg)
                                pybotPrint("[IRC] %s has left the channel" % name, "irc")
                                self.totalUsers -= 1

                        if "MODE" in msg:
                            ev = "user_mode"
                            name = msg.split(' ')[4].replace('\n\r', '')
                            mode = msg.split(' ')[3]
                            self.addMode(name, mode)

                        # when bot gets modded
                        #if (name == self.nick and mode == "+o"):
                        #	self.msg("Pybot has successfully joined your channel as a mod.")
                        #	self.botIsMod = True
                        #elif (name == self.nick and mode == "-o"):
                        #	self.botIsMod = False

                        if "PING" in msg:
                            ev = "server_ping"
                            self.rawmsg("PONG %s\r\n" % self.server) 		# make sure the bot doesnt time out!
                            self.ping_timeout = self.ping_timeout_max

                    else:
                        if ("jtv.tmi.twitch.tv PRIVMSG " + self.channel not in msg):
                            ev = "user_privmsg"
                            if (self.linkgrabber == True):
                                self.linkgrab(msg)

                            self.chat_time = 0 							  	# set timeout time to 0 so bot doesn't leave when there is activity
                        else:
                            ev = "jtv"
                            if ("SPECIALUSER" in msg):						# :jtv PRIVMSG pybot_beta :SPECIALUSER username subscriber
                                text = msg.split("PRIVMSG")[1].replace('%s :' % self.nick, '')
                                name = text.split(" ")[2]
                                type = text.split(" ")[3]

                                if (type not in self.getMode(name)):
                                    #printHTML(name + " is a "+type, "irc")
                                    self.addMode(name, "+"+type)
                                    pybotPrint(name + "is mode " + self.getMode(name))
                            elif ("The moderators of this room are:" in msg):
                                text = msg.split("PRIVMSG")[1].replace('%s :' % self.channel, '').replace("The moderators of this room are:", '')
                                names = text.split(',')
                                for i in names:
                                    self.addMode(i.strip(), "+o")

                    if self.connected == True and ev != "jtv":
                        self.hook(self, msg, ev)
        except Exception as e:
            pybotPrint(e.message)
            self.retry()

    def getLinkBanned(self):
        result = self.mysql.query_r("SELECT name FROM linkBanned WHERE channel = '%s' " % self.channel);
        for name in result:
            self.linkbanned.append(name[0])

    def isLinkBanned(self, name):
        if name in self.linkbanned:
            return True
        else:
            return False

    def linkBan(self, name):
        if name not in self.linkbanned:
            self.mysql.query("INSERT INTO linkBanned values ('%s', '%s')" % (name, self.channel))
            self.msg(name + " can no longer add links")
            self.linkbanned.append(name)

    def addQuote(self, name, text):
        self.mysql.query("INSERT INTO userQuote values (null, '%s', '%s', '%s')" % (self.channel, name, text))

    def getRandomQuote(self):
        result = self.mysql.query_r("SELECT * FROM userQuote WHERE userName = '%s'" % self.channel)
        if (len(result) > 0):
            return result[random.randint(0, len(result)-1)][3]
        return False

    def linkgrab(self, msg):
        name = msg.replace(':', '').split('!')[0].replace('\n\r', '')
        text = msg.split("PRIVMSG")[1].replace('%s :' % self.channel, '')
        filters = ['http://', 'www.', '.com', '.ca', '.org', '.gov', '.on', '.tk']

        if self.isLinkBanned(name) == False:
            for filter in filters:
                if filter in text.lower():
                    print "link found!"
                    self.mysql.query("INSERT INTO link values (null, '%s', '%s', '%s')" % (self.channel, text, name))
                    self.msg(name + ", your link has been grabbed.")
                    break

    def getPrivMsgName(self, text):
        return text.replace(':', '').split('!')[0]

    def addMode(self, user, mode):

        if (user.strip() == self.nick and mode == "+o" and "o" not in self.getMode(user)):
            self.msg("Pybot has successfully joined your channel as a mod.")
            self.botIsMod = True
        elif (user.strip() == self.nick and mode == "-o"):
            self.botIsMod = False

        try:
            if ("+" in mode):
                if mode.replace("+", "") not in self.users[user]:
                    try:
                        self.users[user] += mode.replace("+", "")+ ","
                    except:
                        self.users[user] = mode.replace("+", "")+ ","
            else:
                try:
                    self.users[user] = self.users[user].replace(mode.replace("-", "") + ",", "")
                except: None
        except:
            if ("+" in mode):
                self.users[user] = mode.replace("+", "")+ ","

    def getMode(self, name):
        try:
            return self.users[name]
        except:
            return ""
        return ""

    def isMod(self, name):
        if (name.lower() == self.channel.replace('#', '').lower()):			# if name is host its auto mod, comment this out if you want to test filters on your own channel
            return True
        else:
            try:
                if "o" in self.users[name]:
                    return True
            except:
                return False
        return False

    def getTotalUsers(self):
        return self.totalUsers

    def ping(self):
        while 1:
            if self.connected:
                self.ping_timeout = self.ping_timeout - 1
                if self.ping_timeout <= 0: # timed out!
                    pybotPrint("Bot has timed out!, reconnecting...")
                    self.retry()
            time.sleep(1)

    def isClosed(self):
        return self.closed

    def close(self, reconn = False):
        try:
            self.socket.send("disconnect")
            self.socket.close()
        except:
            self.socket.close()

        self.socket = ""
        self.connected = False
        if (reconn == False): self.closed = True
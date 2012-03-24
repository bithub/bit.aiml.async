# -*- coding: latin-1 -*-
"""This file contains the public interface to the aiml module."""

import os
import sys
import copy
import glob
import random
import re
import string
import time
import threading
import xml.sax
from ConfigParser import ConfigParser

from zope.event import notify

from twisted.python import log
from twisted.internet import defer

import parser as aiml_parser
import subs
import utils
from pattern import PatternMgr
from wordsub import WordSub

from bit.bot.base.events import BotRespondsEvent, PersonSpeaksEvent


class Kernel(object):

    # module constants

    # key of the global session (duh)
    _globalSessionID = "_global"
    # maximum length of the _inputs and _responses lists
    _maxHistorySize = 10
    # maximum number of recursive <srai>/<sr> tags
    # before the response is aborted.
    _maxRecursionDepth = 100

    # special predicate keys

    # keys to a queue (list) of recent user input
    _inputHistory = "_inputHistory"
    # keys to a queue (list) of recent responses.
    _outputHistory = "_outputHistory"
    # Should always be empty in between calls to respond()
    _inputStack = "_inputStack"

    def __init__(self):
        self._verboseMode = True
        self._debugMode = False
        self._version = "PyAIML 0.9.1"
        self._brain = PatternMgr()
        self._respondLock = threading.RLock()
        self._textEncoding = "utf-8"

        # set up the sessions
        self._sessions = {}
        self._addSession(self._globalSessionID)

        # Set up the bot predicates
        self._botPredicates = {}
        self.setBotPredicate("name", "Nameless")

        # set up the word substitutors (subbers):
        self._subbers = {}
        self._subbers['gender'] = WordSub(subs.defaultGender)
        self._subbers['person'] = WordSub(subs.defaultPerson)
        self._subbers['person2'] = WordSub(subs.defaultPerson2)
        self._subbers['normal'] = WordSub(subs.defaultNormal)

        # set up the element processors
        self._elementProcessors = {
            "bot":          self._processBot,
            "condition":    self._processCondition,
            "date":         self._processDate,
            "formal":       self._processFormal,
            "gender":       self._processGender,
            "get":          self._processGet,
            "gossip":       self._processGossip,
            "id":           self._processId,
            "input":        self._processInput,
            "javascript":   self._processJavascript,
            "learn":        self._processLearn,
            "li":           self._processLi,
            "lowercase":    self._processLowercase,
            "person":       self._processPerson,
            "person2":      self._processPerson2,
            "random":       self._processRandom,
            "text":         self._processText,
            "sentence":     self._processSentence,
            "set":          self._processSet,
            "size":         self._processSize,
            "sr":           self._processSr,
            "srai":         self._processSrai,
            "star":         self._processStar,
            "system":       self._processSystem,
            "template":     self._processTemplate,
            "that":         self._processThat,
            "thatstar":     self._processThatstar,
            "think":        self._processThink,
            "topicstar":    self._processTopicstar,
            "uppercase":    self._processUppercase,
            "version":      self._processVersion,
            # AIML extensions
            "eval":         self._processEval,
            # HTML extensions
            "html:br":      self._processBR,
            }

    def bootstrap(self, brainFile=None, learnFiles=[], commands=[]):
        """Prepare a Kernel object for use.

        If a brainFile argument is provided, the Kernel attempts to
        load the brain at the specified filename.

        If learnFiles is provided, the Kernel attempts to load the
        specified AIML files.

        Finally, each of the input strings in the commands list is
        passed to respond().

        """
        start = time.clock()
        if brainFile:
            self.loadBrain(brainFile)

        # learnFiles might be a string, in which case it should be
        # turned into a single-element list.
        learns = learnFiles
        try:
            learns = [learnFiles + ""]
        except:
            pass
        for file in learns:
            self.learn(file)

        # ditto for commands
        cmds = commands
        try:
            cmds = [commands + ""]
        except:
            pass
        for cmd in cmds:
            print self._respond(cmd, self._globalSessionID)

        if self._verboseMode:
            print "Kernel bootstrap completed in %.2f seconds" % (
                time.clock() - start)

    def verbose(self, isVerbose=True):
        """Enable/disable verbose output mode."""
        self._verboseMode = isVerbose

    def debug(self, isDebug=True):
        """Enable/disable dubug output mode."""
        self._debugMode = isDebug

    def version(self):
        """Return the Kernel's version string."""
        return self._version

    def numCategories(self):
        """Return the number of categories the Kernel has learned."""
        # there's a one-to-one mapping between templates and categories
        return self._brain.numTemplates()

    def resetBrain(self):
        """Reset the brain to its initial state.

        This is essentially equivilant to:
            del(kern)
            kern = aiml.Kernel()

        """
        del(self._brain)
        self.__init__()

    def loadBrain(self, filename):
        """Attempt to load a previously-saved 'brain' from the
        specified filename.

        NOTE: the current contents of the 'brain' will be discarded!

        """
        if self._verboseMode:
            print "Loading brain from %s..." % filename,
        start = time.clock()
        self._brain.restore(filename)
        if self._verboseMode:
            end = time.clock() - start
            print "done (%d categories in %.2f seconds)" % (
                self._brain.numTemplates(), end)

    def saveBrain(self, filename):
        """Dump the contents of the bot's brain to a file on disk."""
        if self._verboseMode:
            print "Saving brain to %s..." % filename,
        start = time.clock()
        self._brain.save(filename)
        if self._verboseMode:
            print "done (%.2f seconds)" % (time.clock() - start)

    def getPredicate(self, name, sessionID=_globalSessionID):
        """Retrieve the current value of the predicate 'name' from the
        specified session.

        If name is not a valid predicate in the session, the empty
        string is returned.

        """
        try:
            return self._sessions[sessionID][name]
        except KeyError:
            return ""

    def setPredicate(self, name, value, sessionID=_globalSessionID):
        """Set the value of the predicate 'name' in the specified
        session.

        If sessionID is not a valid session, it will be created. If
        name is not a valid predicate in the session, it will be
        created.

        """
        # add the session, if it doesn't already exist.
        self._addSession(sessionID)
        self._sessions[sessionID][name] = value

    def getBotPredicate(self, name):
        """Retrieve the value of the specified bot predicate.

        If name is not a valid bot predicate, the empty string is returned.

        """
        try:
            return self._botPredicates[name]
        except KeyError:
            return ""

    def setBotPredicate(self, name, value):
        """Set the value of the specified bot predicate.

        If name is not a valid bot predicate, it will be created.

        """
        self._botPredicates[name] = value
        # Clumsy hack: if updating the bot name, we must update the
        # name in the brain as well
        if name == "name":
            self._brain.setBotName(self.getBotPredicate("name"))

    def setTextEncoding(self, encoding):
        """Set the text encoding used when loading
        AIML files (Latin-1, UTF-8, etc.)."""
        self._textEncoding = encoding

    def loadSubs(self, filename):
        """Load a substitutions file.

        The file must be in the Windows-style INI format (see the
        standard ConfigParser module docs for information on this
        format).  Each section of the file is loaded into its own
        substituter.

        """
        inFile = file(filename)
        parser = ConfigParser()
        parser.readfp(inFile, filename)
        inFile.close()
        for s in parser.sections():
            # Add a new WordSub instance for this section.  If one already
            # exists, delete it.
            if s in self._subbers:
                del(self._subbers[s])
            self._subbers[s] = WordSub()
            # iterate over the key,value pairs and add them to the subber
            for k, v in parser.items(s):
                self._subbers[s][k] = v

    def _addSession(self, sessionID):
        """Create a new session with the specified ID string."""
        if sessionID in self._sessions:
            return
        # Create the session.
        self._sessions[sessionID] = {
            # Initialize the special reserved predicates
            self._inputHistory: [],
            self._outputHistory: [],
            self._inputStack: []
        }

    def _deleteSession(self, sessionID):
        """Delete the specified session."""
        if sessionID in  self._sessions:
            self._sessions.pop(sessionID)

    def getSessionData(self, sessionID=None):
        """Return a copy of the session data dictionary for the
        specified session.

        If no sessionID is specified, return a dictionary containing
        *all* of the individual session dictionaries.

        """
        s = None
        if sessionID is not None:
            try:
                s = self._sessions[sessionID]
            except KeyError:
                s = {}
        else:
            s = self._sessions
        return copy.deepcopy(s)

    def learn(self, filename):
        """Load and learn the contents of the specified AIML file.

        If filename includes wildcard characters, all matching files
        will be loaded and learned.

        """
        log.err('bit.aiml.async.kernel: Kernel.learn')
        for f in glob.glob(filename):
            if self._verboseMode:
                print "Loading %s..." % f,
            start = time.clock()
            # Load and parse the AIML file.
            parser = aiml_parser.create_parser()
            handler = parser.getContentHandler()
            handler.setEncoding(self._textEncoding)
            try:
                parser.parse(f)
            except xml.sax.SAXParseException, msg:
                err = "\nFATAL PARSE ERROR in file %s:\n%s\n" % (f, msg)
                sys.stderr.write(err)
                continue
            # store the pattern/template pairs in the PatternMgr.
            for key, tem in handler.categories.items():
                self._brain.add(key, tem)
                if self._debugMode:
                    print "\nk: ", key, "\nt: ", tem
            # Parsing was successful.
            if self._verboseMode:
                print "done (%.2f seconds)" % (time.clock() - start)

    def _createCategory(self, filename):
        """Load and learn the contents of the specified AIML file.

        If filename includes wildcard characters, all matching files
        will be loaded and learned.

        """
        if self._verboseMode:
            print "Adding new Category...",
        start = time.clock()
        # Load and parse the AIML file.
        parser = aiml_parser.create_parser()
        handler = parser.getContentHandler()
        handler.setEncoding(self._textEncoding)

        try:
            parser.parseString(f)
        except xml.sax.SAXParseException, msg:
            err = "\nFATAL PARSE ERROR in file %s:\n%s\n" % (f, msg)
            sys.stderr.write(err)
        # store the pattern/template pairs in the PatternMgr.
        for key, tem in handler.categories.items():
            self._brain.add(key, tem)
            if self._debugMode:
                print "\nk: ", key, "\nt: ", tem
        # Parsing was successful.
        if self._verboseMode:
            print "done (%.2f seconds)" % (time.clock() - start)

    def respond(self, request, input):
        """Return the Kernel's response to the input string."""
        log.msg('bit.aiml.async.kernel: Kernel.respond')

        if len(input) == 0:
            return ""

        notify(PersonSpeaksEvent(self).update(request, input))

        #ensure that input is a unicode string
        try:
            input = input.decode(self._textEncoding, 'replace')
        except UnicodeError:
            pass
        except AttributeError:
            pass

        # prevent other threads from stomping all over us.
        self._respondLock.acquire()

        # FIX: get the session id from the request

        # Add the session, if it doesn't already exist
        self._addSession(request.session_id or _globalSessionID)

        # split the input into discrete sentences
        sentences = utils.sentences(input)

        _responses = []

        def _gotResponses(responses):
            finalResponse = ""
            for ret, response in responses:
                # add the data from this exchange to the history lists
                outputHistory = self.getPredicate(
                    self._outputHistory, request.session_id)
                outputHistory.append(response)
                while len(outputHistory) > self._maxHistorySize:
                    outputHistory.pop(0)
                    self.setPredicate(
                        self._outputHistory, outputHistory, request.session_id)
                # append this response to the final response.
                finalResponse += (response + "  ")
            finalResponse = finalResponse.strip()
            assert(len(self.getPredicate(
                        self._inputStack, request.session_id)) == 0)

            # release the lock and return
            self._respondLock.release()
            notify(BotRespondsEvent(self).update(request, finalResponse))
            try:
                return finalResponse.encode(self._textEncoding)
            except UnicodeError:
                return finalResponse

        def _failed(resp):
            print 'FAILED'
            print resp
            self._respondLock.release()

        for s in sentences:
            # Add the input to the history list before fetching the
            # response, so that <input/> tags work properly.
            inputHistory = self.getPredicate(
                self._inputHistory, request.session_id)
            inputHistory.append(s)
            while len(inputHistory) > self._maxHistorySize:
                inputHistory.pop(0)
            self.setPredicate(
                self._inputHistory, inputHistory, request.session_id)

            # Fetch the response
            _responses.append(self._respond(request, s))
        return defer.DeferredList(
            _responses).addCallback(_gotResponses).addErrback(_failed)

    # This version of _respond() just fetches the response for some input.
    # It does not mess with the input and output histories.  Recursive calls
    # to respond() spawned from tags like <srai> should call this function
    # instead of respond().
    def _respond(self, request, input):
        """Private version of respond(), does the real work."""
        if len(input) == 0:
            return ""

        if self._debugMode:
            print "topic =",
            self.getPredicate("topic", request.session_id), "star =",
            self.getPredicate("star", request.session_id)
        # guard against infinite recursion
        inputStack = self.getPredicate(self._inputStack, request.session_id)
        if len(inputStack) > self._maxRecursionDepth:
            if self._verboseMode:
                err = "WARNING: maximum recursion depth exceeded (input='%s')"\
                    % input.encode(self._textEncoding, 'replace')
                sys.stderr.write(err)
            return ""

        # push the input onto the input stack
        inputStack = self.getPredicate(self._inputStack, request.session_id)
        inputStack.append(input)
        self.setPredicate(self._inputStack, inputStack, request.session_id)

        # run the input through the 'normal' subber
        subbedInput = self._subbers['normal'].sub(input)

        # fetch the bot's previous response, to pass to the match()
        # function as 'that'.
        outputHistory = self.getPredicate(
            self._outputHistory, request.session_id)
        try:
            that = outputHistory[-1]
        except IndexError:
            that = ""

        subbedThat = self._subbers['normal'].sub(that)

        # fetch the current topic
        topic = self.getPredicate("topic", request.session_id)
        subbedTopic = self._subbers['normal'].sub(topic)

        # Determine the final response.
        response = []
        elem = self._brain.match(subbedInput, subbedThat, subbedTopic)

        if self._debugMode:
            print "key =", subbedInput, subbedThat, subbedTopic

        if elem is None:
            response = defer.maybeDeferred(lambda x: x, None)
            if self._verboseMode:
                err = "WARNING: No match found for input: %s\n"\
                    % input.encode(self._textEncoding)
                sys.stderr.write(err)

        else:

            def _gotResponse(resp):
                return (resp.strip() + ' ').strip()

            def _getResponse(elem, session):
                return self._processElement(elem, request)

            response = defer.maybeDeferred(
                _getResponse, elem,
                request.session_id).addCallback(_gotResponse)

        # pop the top entry off the input stack.
        inputStack = self.getPredicate(self._inputStack, request.session_id)
        inputStack.pop()
        self.setPredicate(self._inputStack, inputStack, request.session_id)

        def _failed(resp):
            resp.printTraceback()
            resp.raiseException()

        response.addErrback(_failed)
        return response

    def _processElement(self, elem, request):
        """Process an AIML element.

        The first item of the elem list is the name of the element's
        XML tag.  The second item is a dictionary containing any
        attributes passed to that tag, and their values.  Any further
        items in the list are the elements enclosed by the current
        element's begin and end tags; they are handled by each
        element's handler function.

        """
        try:
            handlerFunc = self._elementProcessors[elem[0]]
        except:
            # Oops -- there's no handler function for this element
            # type!
            if self._verboseMode:
                err = "WARNING: No handler found for <%s> element\n"\
                    % elem[0].encode(self._textEncoding, 'replace')
                sys.stderr.write(err)
            return ""
        return handlerFunc(elem, request)

    ######################################################
    ### Individual element-processing functions follow ###
    ######################################################

    # <bot>
    def _processBot(self, elem, request):
        """Process a <bot> AIML element.

        Required element attributes:
            name: The name of the bot predicate to retrieve.

        <bot> elements are used to fetch the value of global,
        read-only "bot predicates."  These predicates cannot be set
        from within AIML; you must use the setBotPredicate() function.

        """
        attrName = elem[1]['name']
        return self.getBotPredicate(attrName)

    # <condition>
    def _processCondition(self, elem, request):
        """Process a <condition> AIML element.

        Optional element attributes:
            name: The name of a predicate to test.
            value: The value to test the predicate for.

        <condition> elements come in three flavors.  Each has different
        attributes, and each handles their contents differently.

        The simplest case is when the <condition> tag has both a 'name'
        and a 'value' attribute.  In this case, if the predicate
        'name' has the value 'value', then the contents of the element
        are processed and returned.

        If the <condition> element has only a 'name' attribute, then
        its contents are a series of <li> elements, each of which has
        a 'value' attribute.  The list is scanned from top to bottom
        until a match is found.  Optionally, the last <li> element can
        have no 'value' attribute, in which case it is processed and
        returned if no other match is found.

        If the <condition> element has neither a 'name' nor a 'value'
        attribute, then it behaves almost exactly like the previous
        case, except that each <li> subelement (except the optional
        last entry) must now include both 'name' and 'value'
        attributes.

        """
        attr = None
        response = []
        attr = elem[1]

        def _gotResponses(responses):
            _response = ''
            for result, resp in responses:
                if result:
                    _response += resp
                else:
                    resp.printTraceback()
            return _response

        # Case #1: test the value of a specific predicate for a
        # specific value.
        if 'name' in attr and 'value' in attr:
            val = self.getPredicate(attr['name'], request.session_id)
            if val == attr['value']:
                for e in elem[2:]:
                    response.append(
                        defer.maybeDeferred(self._processElement, e, request))
                return defer.DeferredList(response).addCallback(_gotResponses)
        else:
            # Case #2 and #3: Cycle through <li> contents, testing a
            # name and value pair for each one.
            try:
                name = None
                if 'name' in attr:
                    name = attr['name']
                # Get the list of <li> elemnents
                listitems = []
                for e in elem[2:]:
                    if e[0] == 'li':
                        listitems.append(e)
                # if listitems is empty, return the empty string
                if len(listitems) == 0:
                    return ""
                # iterate through the list looking for a condition that
                # matches.
                foundMatch = False

                for li in listitems:
                    try:
                        liAttr = li[1]
                        # if this is the last list item, it's allowed
                        # to have no attributes.  We just skip it for now.
                        if len(liAttr.keys()) == 0 and li == listitems[-1]:
                            continue
                        # get the name of the predicate to test
                        liName = name
                        if liName == None:
                            liName = liAttr['name']
                        # get the value to check against
                        liValue = liAttr['value']
                        # do the test
                        if self.getPredicate(
                            liName, request.session_id) == liValue:
                            foundMatch = True
                            response.append(
                                defer.maybeDeferred(
                                    self._processElement, li, request))
                            break
                    except:
                        # No attributes, no name/value attributes, no
                        # such predicate/session, or processing error.
                        if self._verboseMode:
                            print "Something amiss -- skipping listitem", li
                        raise
                if not foundMatch:
                    # Check the last element of listitems.  If it has
                    # no 'name' or 'value' attribute, process it.
                    try:
                        li = listitems[-1]
                        liAttr = li[1]
                        if not ('name' in liAttr or 'value' in liAttr):
                            response.append(
                                defer.maybeDeferred(
                                    self._processElement, li, request))
                    except:
                        # listitems was empty, no attributes, missing
                        # name/value attributes, or processing error.
                        if self._verboseMode:
                            print "error in default listitem"
                        raise
            except:
                # Some other catastrophic cataclysm
                if self._verboseMode:
                    print "catastrophic condition failure"
                raise
        return defer.DeferredList(response).addCallback(_gotResponses)

    # <date>
    def _processDate(self, elem, request):
        """Process a <date> AIML element.

        <date> elements resolve to the current date and time.  The
        AIML specification doesn't require any particular format for
        this information, so I go with whatever's simplest.

        """
        return time.asctime()

    # <formal>
    def _processFormal(self, elem, request):
        """Process a <formal> AIML element.

        <formal> elements process their contents recursively, and then
        capitalize the first letter of each word of the result.

        """
        response = ""
        for e in elem[2:]:
            response += self._processElement(e, request)
        return string.capwords(response)

    # <gender>
    def _processGender(self, elem, request):
        """Process a <gender> AIML element.

        <gender> elements process their contents, and then swap the
        gender of any third-person singular pronouns in the result.
        This subsitution is handled by the aiml.WordSub module.

        """
        response = ""
        for e in elem[2:]:
            response += self._processElement(e, request)
        return self._subbers['gender'].sub(response)

    # <get>
    def _processGet(self, elem, request):
        """Process a <get> AIML element.

        Required element attributes:
            name: The name of the predicate whose value should be
            retrieved from the specified session and returned.  If the
            predicate doesn't exist, the empty string is returned.

        <get> elements return the value of a predicate from the
        specified session.

        """
        return self.getPredicate(elem[1]['name'], request.session_id)

    # <gossip>
    def _processGossip(self, elem, request):
        """Process a <gossip> AIML element.

        <gossip> elements are used to capture and store user input in
        an implementation-defined manner, theoretically allowing the
        bot to learn from the people it chats with.  I haven't
        descided how to define my implementation, so right now
        <gossip> behaves identically to <think>.

        """
        return self._processThink(elem, request)

    # <id>
    def _processId(self, elem, request):
        """ Process an <id> AIML element.

        <id> elements return a unique "user id" for a specific
        conversation.  In PyAIML, the user id is the name of the
        current session.

        """
        return request.session_id

    # <input>
    def _processInput(self, elem, request):
        """Process an <input> AIML element.

        Optional attribute elements:
            index: The index of the element from the history list to
            return. 1 means the most recent item, 2 means the one
            before that, and so on.

        <input> elements return an entry from the input history for
        the current session.

        """
        inputHistory = self.getPredicate(
            self._inputHistory, request.session_id)
        try:
            index = int(elem[1]['index'])
        except:
            index = 1
        try:
            return inputHistory[-index]
        except IndexError:
            if self._verboseMode:
                err = "No such index %d while processing <input> element.\n"\
                    % index
                sys.stderr.write(err)
            return ""

    # <javascript>
    def _processJavascript(self, elem, request):
        """Process a <javascript> AIML element.

        <javascript> elements process their contents recursively, and
        then run the results through a server-side Javascript
        interpreter to compute the final response.  Implementations
        are not required to provide an actual Javascript interpreter,
        and right now PyAIML doesn't; <javascript> elements are behave
        exactly like <think> elements.

        """
        return self._processThink(elem, request)

    # <learn>
    def _processLearn(self, elem, request):
        """Process a <learn> AIML element.

        <learn> elements process their contents recursively, and then
        treat the result as an AIML file to open and learn.

        """
        filename = ""
        for e in elem[2:]:
            filename += self._processElement(e, request)
        if filename[-5:] == ".aiml":
            self.learn(filename)
        else:
            self._createCategory(filename)
        return ""

    # <li>
    def _processLi(self, elem, request):
        """Process an <li> AIML element.

        Optional attribute elements:
            name: the name of a predicate to query.
            value: the value to check that predicate for.

        <li> elements process their contents recursively and return
        the results. They can only appear inside <condition> and
        <random> elements.  See _processCondition() and
        _processRandom() for details of their usage.

        """

        def _gotResponses(responses):
            _response = ''
            for result, resp in responses:
                if result:
                    _response += resp
                else:
                    resp.printTraceback()
            return _response
        response = []
        for e in elem[2:]:
            response.append(
                defer.maybeDeferred(self._processElement, e, request))
        return defer.DeferredList(response).addCallback(_gotResponses)

    # <lowercase>
    def _processLowercase(self, elem, request):
        """Process a <lowercase> AIML element.

        <lowercase> elements process their contents recursively, and
        then convert the results to all-lowercase.

        """
        response = ""
        for e in elem[2:]:
            response += self._processElement(e, request)
        return string.lower(response)

    # <person>
    def _processPerson(self, elem, request):
        """Process a <person> AIML element.

        <person> elements process their contents recursively, and then
        convert all pronouns in the results from 1st person to 2nd
        person, and vice versa.  This subsitution is handled by the
        aiml.WordSub module.

        If the <person> tag is used atomically (e.g. <person/>), it is
        a shortcut for <person><star/></person>.

        """
        response = ""
        for e in elem[2:]:
            response += self._processElement(e, request)
        if len(elem[2:]) == 0:  # atomic <person/> = <person><star/></person>
            response = self._processElement(['star', {}], request)
        return self._subbers['person'].sub(response)

    # <person2>
    def _processPerson2(self, elem, request):
        """Process a <person2> AIML element.

        <person2> elements process their contents recursively, and then
        convert all pronouns in the results from 1st person to 3rd
        person, and vice versa.  This subsitution is handled by the
        aiml.WordSub module.

        If the <person2> tag is used atomically (e.g. <person2/>), it is
        a shortcut for <person2><star/></person2>.

        """
        response = ""
        for e in elem[2:]:
            response += self._processElement(e, request)
        if len(elem[2:]) == 0:
            # atomic <person2/> = <person2><star/></person2>
            response = self._processElement(['star', {}], request)
        return self._subbers['person2'].sub(response)

    # <random>
    def _processRandom(self, elem, request):
        """Process a <random> AIML element.

        <random> elements contain zero or more <li> elements.  If
        none, the empty string is returned.  If one or more <li>
        elements are present, one of them is selected randomly to be
        processed recursively and have its results returned.  Only the
        chosen <li> element's contents are processed.  Any non-<li>
        contents are ignored.

        """
        listitems = []
        for e in elem[2:]:
            if e[0] == 'li':
                listitems.append(e)
        if len(listitems) == 0:
            return ""

        # select and process a random listitem.
        random.shuffle(listitems)
        return self._processElement(listitems[0], request)

    # <sentence>
    def _processSentence(self, elem, request):
        """Process a <sentence> AIML element.

        <sentence> elements process their contents recursively, and
        then capitalize the first letter of the results.

        """
        response = ""
        for e in elem[2:]:
            response += self._processElement(e, request)
        try:
            response = response.strip()
            words = string.split(response, " ", 1)
            words[0] = string.capitalize(words[0])
            response = string.join(words)
            return response
        except IndexError:
            #response was empty
            return ""

    # <set>
    def _processSet(self, elem, request):
        """Process a <set> AIML element.

        Required element attributes:
            name: The name of the predicate to set.

        <set> elements process their contents recursively, and assign
        the results to a predicate (given by their 'name' attribute)
        in the current session.  The contents of the element are also returned.

        """
        value = ""
        for e in elem[2:]:
            value += self._processElement(e, request)
        self.setPredicate(elem[1]['name'], value, request.session_id)
        return value

    # <size>
    def _processSize(self, elem, request):
        """Process a <size> AIML element.

        <size> elements return the number of AIML categories currently
        in the bot's brain.

        """
        return str(self.numCategories())

    # <sr>
    def _processSr(self, elem, request):
        """Process an <sr> AIML element.

        <sr> elements are shortcuts for <srai><star/></srai>.

        """
        star = self._processElement(['star', {}], request)
        response = self._respond(star, request)
        return response

    # <srai>
    def _processSrai(self, elem, request):
        """Process a <srai> AIML element.

        <srai> elements recursively process their contents, and then
        pass the results right back into the AIML interpreter as a new
        piece of input.  The results of this new input string are
        returned.

        """

        def _gotResponses(responses):
            _response = ''
            for result, resp in responses:
                if result:
                    _response += resp
                else:
                    resp.printTraceback()
            return self._respond(request, _response)
        newInput = []
        for e in elem[2:]:
            newInput.append(
                defer.maybeDeferred(self._processElement, e, request))
        return defer.DeferredList(newInput).addCallback(_gotResponses)

    # <star>
    def _processStar(self, elem, request):
        """Process a <star> AIML element.

        Optional attribute elements:
            index: Which "*" character in the current pattern should
            be matched?

        <star> elements return the text fragment matched by the "*"
        character in the current input pattern.  For example, if the
        input "Hello Tom Smith, how are you?" matched the pattern
        "HELLO * HOW ARE YOU", then a <star> element in the template
        would evaluate to "Tom Smith".

        """
        try:
            index = int(elem[1]['index'])
        except KeyError:
            index = 1
        # fetch the user's last input
        inputStack = self.getPredicate(self._inputStack, request.session_id)
        input = self._subbers['normal'].sub(inputStack[-1])
        # fetch the Kernel's last response (for 'that' context)
        outputHistory = self.getPredicate(
            self._outputHistory, request.session_id)
        try:
            that = self._subbers['normal'].sub(outputHistory[-1])
        except:
            # there might not be any output yet
            that = ""
        topic = self.getPredicate("topic", request.session_id)
        response = self._brain.star(
            "star", input, that, topic, index)
        return response

    # <template>
    def _processTemplate(self, elem, request):
        """Process a <template> AIML element.

        <template> elements recursively process their contents, and
        return the results.  <template> is the root node of any AIML
        response tree.

        """
        response = []

        def _gotResponses(responses):
            _response = ''
            for result, resp in responses:
                if result:
                    _response += resp
                else:
                    resp.printTraceback()
            return _response

        for e in elem[2:]:
            response.append(
                defer.maybeDeferred(self._processElement, e, request))
        return defer.DeferredList(response).addCallback(_gotResponses)

    # text
    def _processText(self, elem, request):
        """Process a raw text element.

        Raw text elements aren't really AIML tags. Text elements cannot contain
        other elements; instead, the third item of the 'elem' list is a text
        string, which is immediately returned. They have a single attribute,
        automatically inserted by the parser, which indicates whether
        whitespace in the text should be preserved or not.

        """
        try:
            elem[2] + ""
        except TypeError:
            raise TypeError("Text element contents are not text")

        # If the the whitespace behavior for this element is "default",
        # we reduce all stretches of >1 whitespace characters to a single
        # space.  To improve performance, we do this only once for each
        # text element encountered, and save the results for the future.
        if elem[1]["xml:space"] == "default":
            elem[2] = re.sub("\s+", " ", elem[2])
            elem[1]["xml:space"] = "preserve"
        return elem[2]

    # <that>
    def _processThat(self, elem, request):
        """Process a <that> AIML element.

        Optional element attributes:
            index: Specifies which element from the output history to
            return.  1 is the most recent response, 2 is the next most
            recent, and so on.

        <that> elements (when they appear inside <template> elements)
        are the output equivilant of <input> elements; they return one
        of the Kernel's previous responses.

        """
        outputHistory = self.getPredicate(
            self._outputHistory, request.session_id)
        index = 1
        try:
            # According to the AIML spec, the optional index attribute
            # can either have the form "x" or "x,y". x refers to how
            # far back in the output history to go.  y refers to which
            # sentence of the specified response to return.
            index = int(elem[1]['index'].split(',')[0])
        except:
            pass
        try:
            return outputHistory[-index]
        except IndexError:
            if self._verboseMode:
                err = "No such index %d while processing <that> element.\n"\
                    % index
                sys.stderr.write(err)
            return ""

    # <thatstar>
    def _processThatstar(self, elem, request):
        """Process a <thatstar> AIML element.

        Optional element attributes:
            index: Specifies which "*" in the <that> pattern to match.

        <thatstar> elements are similar to <star> elements, except
        that where <star/> returns the portion of the input string
        matched by a "*" character in the pattern, <thatstar/> returns
        the portion of the previous input string that was matched by a
        "*" in the current category's <that> pattern.

        """
        try:
            index = int(elem[1]['index'])
        except KeyError:
            index = 1
        # fetch the user's last input
        inputStack = self.getPredicate(self._inputStack, request.session_id)
        input = self._subbers['normal'].sub(inputStack[-1])
        # fetch the Kernel's last response (for 'that' context)
        outputHistory = self.getPredicate(
            self._outputHistory, request.session_id)
        try:
            that = self._subbers['normal'].sub(outputHistory[-1])
        except:
            # there might not be any output yet
            that = ""
        topic = self.getPredicate("topic", request.session_id)
        response = self._brain.star("thatstar", input, that, topic, index)
        return response

    # <think>
    def _processThink(self, elem, request):
        """Process a <think> AIML element.

        <think> elements process their contents recursively, and then
        discard the results and return the empty string.  They're
        useful for setting predicates and learning AIML files without
        generating any output.

        """
        for e in elem[2:]:
            self._processElement(e, request)
        return ""

    # <topicstar>
    def _processTopicstar(self, elem, request):
        """Process a <topicstar> AIML element.

        Optional element attributes:
            index: Specifies which "*" in the <topic> pattern to match.

        <topicstar> elements are similar to <star> elements, except
        that where <star/> returns the portion of the input string
        matched by a "*" character in the pattern, <topicstar/>
        returns the portion of current topic string that was matched
        by a "*" in the current category's <topic> pattern.

        """
        try:
            index = int(elem[1]['index'])
        except KeyError:
            index = 1
        # fetch the user's last input
        inputStack = self.getPredicate(self._inputStack, request.session_id)
        input = self._subbers['normal'].sub(inputStack[-1])
        # fetch the Kernel's last response (for 'that' context)
        outputHistory = self.getPredicate(
            self._outputHistory, request.session_id)
        try:
            that = self._subbers['normal'].sub(outputHistory[-1])
        except:
            # there might not be any output yet
            that = ""
        topic = self.getPredicate("topic", request.session_id)
        response = self._brain.star("topicstar", input, that, topic, index)
        return response

    # <uppercase>
    def _processUppercase(self, elem, request):
        """Process an <uppercase> AIML element.

        <uppercase> elements process their contents recursively, and
        return the results with all lower-case characters converted to
        upper-case.

        """
        response = ""
        for e in elem[2:]:
            response += self._processElement(e, request)
        return string.upper(response)

    # <version>
    def _processVersion(self, elem, request):
        """Process a <version> AIML element.

        <version> elements return the version number of the AIML
        interpreter.

        """
        return self.version()

    #
    def _elem2XML(self, elem, request):
        """Convert element to XML
        except <eval> as well as <text>

        """
        tag = elem[0][0]
        if tag == "text" or tag == "eval":
            response = ""
            for e in elem[2:]:
                response += self._processElement(e, request)
            return response
        response = "<" + tag
        attr = None
        attr = elem[1]
        if len(attr) > 0:
            for k, v in attr.items():
                response += " \"%s\"=\"%s\"" % (k, v)
        response += ">\n"
        for e in elem[2:]:
            response += self._elem2XML(e, request)
        response += "</" + tag + ">\n"
        return response

    # <eval>
    def _processEval(self, elem, request):
        """Process a <eval> AIML-extension element.

        <eval>, like <template> elements, recursively process their contents,
        and return the results.  <eval> is the special child node of <learn>.

        """
        response = ""
        for e in elem[2:]:
            response += self._processElement(e, request)
        return response

    # <html:br>
    def _processBR(self, elem, request):
        """Process a <html:br> AIML element.

        <html:br> elements return the new-line.

        """
        return "\n"

    # <system>
    def _processSystem(self, elem, request):
        """Process a <system> AIML element.

        <system> elements process their contents recursively, and then
        attempt to execute the results as a shell command on the
        server.  The AIML interpreter blocks until the command is
        complete, and then returns the command's output.

        For cross-platform compatibility, any file paths inside
        <system> tags should use Unix-style forward slashes ("/") as a
        directory separator.

        """
        # build up the command string
        command = ""
        for e in elem[2:]:
            command += self._processElement(e, request.session_id)

        #HACK
        from zope.dottedname.resolve import resolve

        #inputStack = self.getPredicate(self._inputStack, request.session_id)
        #input = self._subbers['normal'].sub(inputStack[-1])
        # fetch the Kernel's last response (for 'that' context)
        #outputHistory
        # = self.getPredicate(self._oustputHistory, request.session_id)
        #try: that = self._subbers['normal'].sub(outputHistory[-1])
        #except: that = "" # there might not be any output yet
        #topic = self.getPredicate("topic", request.session_id)
        if '.' in command and not '/' in command:
            code = resolve(command)
            if code:
                _code = code(self)

                def _complete(result):
                    _code.complete()
                    return result or ''
                return defer.maybeDeferred(
                    _code.parse, self, request, elem).addCallback(_complete)

        #/HACK

        # normalize the path to the command.  Under Windows, this
        # switches forward-slashes to back-slashes; all system
        # elements should use unix-style paths for cross-platform
        # compatibility.
        #executable,args = command.split(" ", 1)
        #executable = os.path.normpath(executable)
        #command = executable + " " + args
        command = os.path.normpath(command)

        # execute the command.
        response = ""
        try:
            out = os.popen(command)
        except RuntimeError, msg:
            if self._verboseMode:
                err = "WARNING: RuntimeError while processing "
                + " \"system\" element:\n%s\n" \
                    % msg.encode(self._textEncoding, 'replace')
                sys.stderr.write(err)
            return """ There was an error while computing my response.
 Please inform my botmaster."""
        for line in out:
            response += line + "\n"
        response = string.join(response.splitlines()).strip()
        return response


##################################################
### Self-test functions follow                 ###
##################################################
def _testTag(kern, tag, input, outputList):
    """Tests 'tag' by feeding the Kernel 'input'.  If the result
    matches any of the strings in 'outputList', the test passes.

    """
    global _numTests, _numPassed
    _numTests += 1
    print "Testing <" + tag + ">:",
    response = kern.respond(input).decode(kern._textEncoding)
    if response in outputList:
        print "PASSED"
        _numPassed += 1
        return True
    else:
        print "FAILED (response: '%s')"\
            % response.encode(kern._textEncoding, 'replace')
        return False

if __name__ == "__main__":
    # Run some self-tests
    k = Kernel()
    k.bootstrap(learnFiles="self-test.aiml")

    global _numTests, _numPassed
    _numTests = 0
    _numPassed = 0

    _testTag(k, 'bot', 'test bot', ["My name is Nameless"])

    k.setPredicate('gender', 'male')
    _testTag(k, 'condition test #1', 'test condition name value',
             ['You are handsome'])
    k.setPredicate('gender', 'female')
    _testTag(k,
             'condition test #2', 'test condition name value',
             [''])
    _testTag(k, 'condition test #3', 'test condition name',
             ['You are beautiful'])
    k.setPredicate('gender', 'robot')
    _testTag(k,
             'condition test #4', 'test condition name',
             ['You are genderless'])
    _testTag(k,
             'condition test #5', 'test condition', ['You are genderless'])
    k.setPredicate('gender', 'male')
    _testTag(k,
             'condition test #6', 'test condition', ['You are handsome'])

    # the date test will occasionally fail if the original and "test"
    # times cross a second boundary.  There's no good way to avoid
    # this problem and still do a meaningful test, so we simply
    # provide a friendly message to be printed if the test fails.
    date_warning = """
    NOTE: the <date> test will occasionally report failure even if it
    succeeds.  So long as the response looks like a date/time string,
    there's nothing to worry about.
    """
    if not _testTag(k, 'date', 'test date',
                    ["The date is %s" % time.asctime()]):
        print date_warning

    _testTag(k, 'formal', 'test formal', ["Formal Test Passed"])
    _testTag(k, 'gender', 'test gender',
             ["He'd told her he heard that her hernia is history"])
    _testTag(k, 'get/set',
             'test get and set', ["I like cheese. My favorite food is cheese"])
    _testTag(k, 'gossip',
             'test gossip', ["Gossip is not yet implemented"])
    _testTag(k, 'id', 'test id', ["Your id is _global"])
    _testTag(k, 'input',
             'test input', ['You just said: test input'])
    _testTag(k, 'javascript',
             'test javascript', ["Javascript is not yet implemented"])
    _testTag(k, 'lowercase',
             'test lowercase', ["The Last Word Should Be lowercase"])
    _testTag(k, 'person',
             'test person',
             ['HE think i knows that my actions threaten him and his.'])
    _testTag(k, 'person2',
             'test person2',
             ['YOU think me know that my actions threaten you and yours.'])
    _testTag(k, 'person2 (no contents)',
             'test person2 I Love Lucy', ['YOU Love Lucy'])
    _testTag(k, 'random',
             'test random', ["response #1", "response #2", "response #3"])
    _testTag(k, 'random empty',
             'test random empty', ["Nothing here!"])
    _testTag(k, 'sentence',
             "test sentence", ["My first letter should be capitalized."])
    _testTag(k, 'size',
             "test size", ["I've learned %d categories" % k.numCategories()])
    _testTag(k, 'sr',
             "test sr test srai", ["srai results: srai test passed"])
    _testTag(k, 'sr nested',
             "test nested sr test srai", ["srai results: srai test passed"])
    _testTag(k, 'srai',
             "test srai", ["srai test passed"])
    _testTag(k, 'srai infinite',
             "test srai infinite", [""])
    _testTag(k, 'star test #1',
             'You should test star begin', ['Begin star matched: You should'])
    _testTag(k, 'star test #2',
             'test star creamy goodness middle',
             ['Middle star matched: creamy goodness'])
    _testTag(k, 'star test #3',
             'test star end the credits roll',
             ['End star matched: the credits roll'])
    _testTag(k, 'star test #4',
             'test star having multiple stars in '
             + 'a pattern makes me extremely happy',
             ['Multiple stars matched: having, '
              + ' stars in a pattern, extremely happy'])
    _testTag(k, 'system',
             "test system", ["The system says hello!"])
    _testTag(k, 'that test #1',
             "test that", ["I just said: The system says hello!"])
    _testTag(k, 'that test #2',
             "test that", ["I have already answered this question"])
    _testTag(k, 'thatstar test #1',
             "test thatstar", ["I say beans"])
    _testTag(k, 'thatstar test #2',
             "test thatstar", ["I just said \"beans\""])
    _testTag(k, 'thatstar test #3',
             "test thatstar multiple",
             ['I say beans and franks for everybody'])
    _testTag(k, 'thatstar test #4',
             "test thatstar multiple", ['Yes, beans and franks for all!'])
    _testTag(k, 'think', "test think", [""])
    k.setPredicate("topic", "fruit")
    _testTag(k, 'topic',
             "test topic", ["We were discussing apples and oranges"])
    k.setPredicate("topic", "Soylent Green")
    _testTag(k, 'topicstar test #1',
             'test topicstar', ["Solyent Green is made of people!"])
    k.setPredicate("topic", "Soylent Ham and Cheese")
    _testTag(k, 'topicstar test #2',
             'test topicstar multiple',
             ["Both Soylents Ham and Cheese are made of people!"])
    _testTag(k, 'unicode support',
             u"���Ϻ�", [u"Hey, you speak Chinese! ���Ϻ�"])
    _testTag(k, 'uppercase',
             'test uppercase', ["The Last Word Should Be UPPERCASE"])
    _testTag(k, 'version',
             'test version', ["PyAIML is version %s" % k.version()])
    _testTag(k, 'whitespace preservation',
             'test whitespace',
             ["Extra   Spaces\n   Rule!   (but not in here!)"
              + "    But   Here   They   Do!"])

    # Report test results
    print "--------------------"
    if _numTests == _numPassed:
        print "%d of %d tests passed!" % (_numPassed, _numTests)
    else:
        print "%d of %d tests passed (see above for detailed errors)" \
            % (_numPassed, _numTests)

    # Run an interactive interpreter
    #print "\nEntering interactive mode (ctrl-c to exit)"
    #while True: print k.respond(raw_input("> "))


from zope.interface import Interface as I


class IAgents(I):
    pass

class ISubscriptions(I):
    pass


class IRoles(I):
    pass

class IIRCBot(I):
    pass

class IIRCRequest(I):
    pass

class INameResolver(I):
    pass

class ICommand(I):
    pass

class ISocketRequest(I):
    pass

class IBotSocket(I):
    pass

class IWebRoot(I):
    pass

class ISQLQuery(I):
    pass

class IFlatten(I):
    pass

class IDataBrain(I):
    pass

class IDataRecord(I):
    pass


class IIntelligent(I):
    pass

class IBotAgent(I):
    pass

class IJabber(I):
    pass

class IHTMLResources(I):
    pass

class IWebImages(I):
    pass

class IWebFolder(I):
    pass

class IWebCSS(I):
    pass

class IWebJS(I):
    pass

class IWebHTML(I):
    pass

class IWebJPlates(I):
    pass

class IJPlates(I):
    pass

class IJSON(I):
    pass

class IData(I):
    pass

class IDataProvider(I):
    pass

class ISessions(I):
    pass

class ISession(I):
    pass

class IWebRoot(I):
    pass


class IMUCBot(I):
    pass


class IAIMLMacro(I):
    pass

class IGroupOfPeople(I):
    """ group of people, an organisation or company """

class IMembers(I):
    """ possible buddies 8) """

class IMember(I):
    """ possible buddies 8) """

class IGroup(I):
    """ possible buddies 8) """        


class IMemory(I):
    """ persistent information """


class IGroups(I):
    """ possible buddies 8) """    

class ICurateBotProtocol(I):
    """ curate command """

class IBotRequest(I):
    """ curate command """

# A decentralized price discovery model with random matching

#===============
# SETUP
#===============

from model import Helipad
from utility import CobbDouglas
from math import sqrt, exp, floor
import random

heli = Helipad()
heli.order = 'random'

heli.addParameter('ratio', 'Log Endowment Ratio', 'slider', dflt=0, opts={'low': -3, 'high': 3, 'step': 0.5})
heli.addGood('shmoo','119900', lambda breed: random.randint(1,1000))
heli.addGood('soma', '990000', lambda breed: random.randint(1,floor(exp(heli.param('ratio'))*1000)))

#===============
# BEHAVIOR
#===============

def agentInit(agent, model):
	agent.lastPeriod = 0	
	agent.utility = CobbDouglas(['shmoo', 'soma'])
heli.addHook('agentInit', agentInit)

def agentStep(agent, model, stage):
	if agent.lastPeriod == model.t: return #Already traded
	partner = random.choice(model.agents['agent']);
	while partner.lastPeriod == model.t: partner = random.choice(model.agents['agent']) #Don't trade with someone who's already traded
	
	myEndowU = agent.utility.calculate({'soma': agent.goods['soma'], 'shmoo': agent.goods['shmoo']})
	theirEndowU = partner.utility.calculate({'soma': partner.goods['soma'], 'shmoo': partner.goods['shmoo']})
	
	#Get the endpoints of the contract curve
	#Contract curve isn't linear unless the CD exponents are both 0.5. If not, *way* more complicated
	cc1Soma = myEndowU * ((agent.goods['soma']+partner.goods['soma'])/(agent.goods['shmoo']+partner.goods['shmoo'])) ** 0.5
	cc2Soma = agent.goods['soma'] + partner.goods['soma'] - theirEndowU  * ((agent.goods['soma']+partner.goods['soma'])/(agent.goods['shmoo']+partner.goods['shmoo'])) ** 0.5
	cc1Shmoo = ((agent.goods['shmoo']+partner.goods['shmoo'])/(agent.goods['soma']+partner.goods['soma'])) * cc1Soma
	cc2Shmoo = ((agent.goods['shmoo']+partner.goods['shmoo'])/(agent.goods['soma']+partner.goods['soma'])) * cc2Soma
		
	#Calculate demand – split the difference on the contract curve
	somaDemand = (cc1Soma+cc2Soma)/2 - agent.goods['soma']
	shmooDemand = (cc1Shmoo+cc2Shmoo)/2 - agent.goods['shmoo']
	
	#Do the trades
	if abs(somaDemand) > 0.1 and abs(shmooDemand) > 0.1:
		agent.trade(partner, 'soma', -somaDemand, 'shmoo', shmooDemand)		
		agent.lastPrice = -somaDemand/shmooDemand
		partner.lastPrice = -somaDemand/shmooDemand
	else:
		agent.lastPrice = None
		partner.lastPrice = None
			
	#Record data and don't trade again this period
	agent.lastPeriod = model.t
	partner.lastPeriod = model.t
	agent.utils = agent.utility.consume({'soma': agent.goods['soma'], 'shmoo': agent.goods['shmoo']})
	partner.utils = partner.utility.consume({'soma': partner.goods['soma'], 'shmoo': partner.goods['shmoo']})
	
	agent.somaTrade = abs(somaDemand)
	agent.shmooTrade = abs(shmooDemand)
	partner.somaTrade = 0 #Don't double count
	partner.shmooTrade = 0
	
heli.addHook('agentStep', agentStep)

#Stop the model when we're basically equilibrated
def modelStep(model, stage):
	if model.t > 1 and model.data.getLast('shmooTrade') < 20 and model.data.getLast('somaTrade') < 20:
		model.gui.terminate()
heli.addHook('modelStep', modelStep)

#===============
# CONFIGURATION
#===============

heli.data.addReporter('price', heli.data.agentReporter('lastPrice', 'agent', stat='gmean', percentiles=[0,100]))
heli.data.addReporter('somaTrade', heli.data.agentReporter('somaTrade', 'agent', stat='sum'))
heli.data.addReporter('shmooTrade', heli.data.agentReporter('shmooTrade', 'agent', stat='sum'))
heli.addSeries('prices', 'price', 'Soma/Shmoo Price', '119900')
heli.addSeries('demand', 'shmooTrade', 'Shmoo Trade', '990000')
heli.addSeries('demand', 'somaTrade', 'Soma Trade', '000099')

heli.defaultPlots = ['prices', 'demand', 'utility']

heli.launchGUI()
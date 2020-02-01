# For instructions on how to run, see https://cameronharwick.com/running-a-python-abm/
# Download the paper at https://ssrn.com/abstract=2545488
# 
# #Differences from the NetLogo version:
# -Target inventory calculated as 1.5 std dev above the mean demand of the last 50 periods
# -Banking model exists and is somewhat stable
# -Code is refactored to make it simple to add agent classes
# -Demand for real balances is mediated through a CES utility function rather than being stipulated ad hoc
#
#TODO: Use multiprocessing to run the graphing in a different process

from collections import namedtuple
from itertools import combinations
from colour import Color
import pandas

from model import Helipad
from math import sqrt
from agent import * #Necessary to register primitives
heli = Helipad()

#========
# THE BANK PRIMITIVE
#========

#Have to specify this first for it to be available…
class Bank():
	def __init__(self, breed, id, model):
		self.unique_id = id
		self.model = model
		
		self.reserves = 0
		self.i = .1				#Per-period interest rate
		self.targetRR = 0.25
		self.lastWithdrawal = 0
		self.inflation = 0
		self.accounts = {}		#Liabilities
		self.credit = {}		#Assets
		
		self.dif = 0			#How much credit was rationed
		self.defaultTotal = 0
		self.pLast = 50 		#Initial price level, equal to average of initial prices
		
			
	def balance(self, customer):
		if customer.unique_id in self.accounts: return self.accounts[customer.unique_id]
		else: return 0
	
	def setupAccount(self, customer):
		if customer.unique_id in self.accounts: return False		#If you already have an account
		self.accounts[customer.unique_id] = 0						#Liabilities
		self.credit[customer.unique_id] = Loan(customer, self)		#Assets
	
	#Assets and liabilities should return the same thing
	#Any difference gets disbursed as interest on deposits
	@property
	def assets(self):
		a = self.reserves
		for uid, l in self.credit.items():
			a += l.owe
		return a
	
	@property
	def liabilities(self):
		return sum(list(self.accounts.values())) #Values returns a dict_values object, not a list. So wrap it in list()
	
	@property
	def loans(self):
		return self.assets - self.reserves
	
	@property
	def reserveRatio(self):
		l = self.liabilities
		if l == 0: return 1
		else: return self.reserves / l
		
	@property
	def realInterest(self):
		return self.i - self.inflation
	
	@realInterest.setter
	def realInterest(self, value):
		self.i = value + self.inflation
	
	def deposit(self, customer, amt):
		if amt == 0: return 0
		if -amt > self.reserves: amt = 0.1 - self.reserves
		# print('Reserves are $', self.reserves)
		# if self.reserves > 0: print("Expanding" if amt>0 else "Contracting","by $",abs(amt),"which is ",abs(amt)/self.reserves*100,"% of reserves")
		
		if amt > customer.goods[self.model.moneyGood]: amt = customer.goods[self.model.moneyGood]
		customer.goods[self.model.moneyGood] -= amt	#Charge customer
		self.reserves += amt						#Deposit cash
		self.accounts[customer.unique_id] += amt	#Credit account
		
		# print('Now reserves are $',self.reserves)
		return amt
	
	def withdraw(self, customer, amt):
		self.deposit(customer, -amt)
		self.lastWithdrawal += amt
	
	def transfer(self, customer, recipient, amt):		
		if self.accounts[customer.unique_id] < amt: amt = self.accounts[customer.unique_id]
		self.accounts[customer.unique_id] -= amt
		self.accounts[recipient.unique_id] += amt
		return amt
	
	def borrow(self, customer, amt):
		if amt < 0.01: return 0 #Skip blanks and float errors
		l = self.credit[customer.unique_id]
				
		#Refinance anything with a higher interest rate
		for n,loan in enumerate(l.loans):
			if loan['i'] >= self.i:
				amt += loan['amount']
				del l.loans[n]
				
		#Increase assets
		l.loans.append({
			'amount': amt,
			'i': self.i
		})
		
		self.accounts[customer.unique_id] += amt	#Increase liabilities
		
		return amt									#How much you actually borrowed
	
	#Returns the amount you actually pay – the lesser of amt or your outstanding balance
	def amortize(self, customer, amt):
		if amt < 0.001: return 0			#Skip blanks and float errors
		l = self.credit[customer.unique_id]	#Your loan object
		l.amortizeAmt += amt				#Count it toward minimum repayment
		leftover = amt
			
		#Reduce assets; amortize in the order borrowed
		while leftover > 0 and len(l.loans) > 0:
			if leftover >= l.loans[0]['amount']:
				leftover -= l.loans[0]['amount']
				del l.loans[0]
			else:
				l.loans[0]['amount'] -= leftover
				leftover = 0
			
		self.accounts[customer.unique_id] -= (amt - leftover)	#Reduce liabilities
		
		return amt - leftover									#How much you amortized
	
	def step(self, stage):
		self.lastWithdrawal = 0
		for l in self.credit: self.credit[l].step(stage)
				
		#Pay interest on deposits
		lia = self.liabilities
		profit = self.assets - lia
		if profit > self.model.param('agents_agent'):
			print('Disbursing profit of $',profit)
			for id, a in self.accounts.items():
				self.accounts[id] += profit/lia * a
		
		# #Set target reserve ratio
		# wd = self.model.data.getLast('withdrawals', 50)
		# mn, st = wd.mean(), wd.std()
		# if isnan(mn) or isnan(st): mn, st = .1, .1
		# ttargetRR = (mn + 2 * st) / lia
		# self.targetRR = (self.targetRR + 49*ttargetRR)/50
	
		#Calculate inflation as the unweighted average price change over all goods
		if self.model.t >= 2:
			inflation = self.model.cb.P/self.pLast - 1
			self.pLast = self.model.cb.P	#Remember the price from this period before altering it for the next period
			self.inflation = (19 * self.inflation + inflation) / 20		#Decaying average
	
		#Set interest rate and/or minimum repayment schedule
		#Count potential borrowing in the interest rate adjustment
		targeti = self.i * self.targetRR / (self.reserveRatio)
	
		#Adjust in proportion to the rate of reserve change
		#Positive deltaReserves indicates falling reserves; negative deltaReserves rising inventory
		if self.model.t > 2:
			deltaReserves = (self.lastReserves - self.reserves)/self.model.cb.P
			targeti *= (1 + deltaReserves/(20 ** self.model.param('pSmooth')))
		self.i = (self.i * 24 + targeti)/25										#Interest rate stickiness
	
		self.lastReserves = self.reserves
			
		#Upper and lower interest rate bounds
		if self.i > 1 + self.inflation: self.i = 1 + self.inflation				#interest rate cap at 100%
		if self.i < self.inflation + 0.005: self.i = self.inflation + 0.005		#no negative real rates
		if self.i < 0.005: self.i = 0.005										#no negative nominal rates

class Loan():
	def __init__(self, customer, bank):
		self.customer = customer
		self.bank = bank
		self.model = bank.model
		self.loans = []
		self.amortizeAmt = 0
	
	@property
	def owe(self):
		amt = 0
		for l in self.loans: amt += l['amount']
		return amt
	
	def step(self, stage):
		#Charge the minimum repayment if the agent hasn't already amortized more than that amount
		minRepay = 0
		for l in self.loans:
			iLoan = l['amount'] * l['i']
			minRepay += iLoan				#You have to pay at least the interest each period
			l['amount'] += iLoan			#Roll over the remainder at the original interest rate
		
		#If they haven't paid the minimum this period, charge it
		amtz = minRepay - self.amortizeAmt
		defaulted = False
		if amtz > 0:
			if amtz > self.bank.accounts[self.customer.unique_id]:	#Can't charge them more than they have in the bank
				defaulted = True
				amtz = self.bank.accounts[self.customer.unique_id]
				# print(self.model.t, ': Agent', self.customer.unique_id, 'defaulted $', self.owe - amtz)
			self.bank.amortize(self.customer, amtz)
			if defaulted:
				for n, l in enumerate(self.loans):
					self.loans[n]['amount'] /= 2
					self.bank.defaultTotal += l['amount']/2
					##Cap defaults at the loan amount. Otherwise if i>1, defaulting results in negative debt
					# if l['i'] >= 1:
					# 	self.bank.defaultTotal += l['amount']
					# 	del self.loans[n]
					# else:
					# 	l['amount'] -= l['amount'] * l['i']
					# 	self.bank.defaultTotal += l['amount'] * l['i']
				
		self.amortizeAmt = 0

#===============
# CONFIGURATION
#===============

heli.addPrimitive('bank', Bank, dflt=1, low=0, high=10, priority=1)
heli.addPrimitive('store', Store, dflt=1, low=0, high=10, priority=2)
heli.addPrimitive('agent', Agent, dflt=50, low=1, high=100, priority=3)

# Configure how many breeds there are and what good each consumes
# In this model, goods and breeds correspond, but they don't necessarily have to
breeds = [
	('hobbit', 'jam', 'D73229'),
	('dwarf', 'axe', '2D8DBE'),
	# ('orc', 'flesh', '664411'),
	# ('elf', 'lembas', 'CCBB22')
]
AgentGoods = {}
for b in breeds:
	heli.addBreed(b[0], b[2], prim='agent')
	heli.addGood(b[1], b[2])
	AgentGoods[b[0]] = b[1] #Hang on to this list for future looping
M0 = 120000
heli.addGood('cash', '009900', money=True)

heli.order = 'random'

#Disable the irrelevant checkboxes if the banking model isn't selected
#Callback for the dist parameter
def bankChecks(gui, val=None):
	nobank = gui.model.param('dist')!='omo'
	gui.model.param('agents_bank', 0 if nobank else 1)
	for i in ['debt', 'rr', 'i']:
		gui.checks[i].disabled(nobank)
	for b in gui.model.primitives['agent']['breeds'].keys():
		gui.sliders['breed_agent-liqPref-'+b].config(state='disabled' if nobank else 'normal')

#Since the param callback takes different parameters than the GUI callback
def bankCheckWrapper(model, var, val):
	bankChecks(model.gui, val)

heli.addHook('terminate', bankChecks)		#Reset the disabled checkmarks when terminating a model
heli.addHook('GUIPostInit', bankChecks)	#Set the disabled checkmarks on initialization

# UPDATE CALLBACKS

def storeUpdater(model, var, val):
	if model.hasModel:
		for s in model.agents['store']:
			setattr(s, var, val)

def ngdpUpdater(model, var, val):
	if model.hasModel: model.cb.ngdpTarget = val if not val else model.cb.ngdp

def rbalUpdater(model, var, breed, val):
	if model.hasModel:
		if var=='rbd':
			beta = val/(1+val)
			for a in model.agents['agent']:
				if hasattr(a, 'utility') and a.breed == breed:
					a.utility.coeffs['rbal'] = beta
					a.utility.coeffs['good'] = 1-beta
		elif var=='liqPref':
			for a in model.agents['agent']:
				if a.breed == breed:
					a.liqPref = val
				
#Set up the info for the sliders on the control panel
#These variables attach to the Helicopter object
#Each parameter requires a corresponding routine in Helicopter.updateVar()
heli.addParameter('ngdpTarget', 'NGDP Target', 'check', dflt=False, callback=ngdpUpdater)
heli.addParameter('dist', 'Distribution', 'menu', dflt='prop', opts={
	'prop': 'Helicopter/Proportional',
	'lump': 'Helicopter/Lump Sum',
	'omo': 'Open Market Operation'
}, runtime=False, callback=bankCheckWrapper)

heli.params['agents_bank'][1]['type'] = 'hidden'
heli.params['agents_store'][1]['type'] = 'hidden'

heli.addParameter('pSmooth', 'Price Smoothness', 'slider', dflt=1.5, opts={'low': 1, 'high': 3, 'step': 0.05}, callback=storeUpdater)
heli.addParameter('wStick', 'Wage Stickiness', 'slider', dflt=10, opts={'low': 1, 'high': 50, 'step': 1}, callback=storeUpdater)
heli.addParameter('kImmob', 'Capital Immobility', 'slider', dflt=100, opts={'low': 1, 'high': 150, 'step': 1}, callback=storeUpdater)
#Low Es means the two are complements (0=perfect complements)
#High Es means the two are substitutes (infinity=perfect substitutes)
#Doesn't really affect anything though – even utility – so don't bother exposing it
heli.addParameter('sigma', 'Elast. of substitution', 'hidden', dflt=.5, opts={'low': 0, 'high': 10, 'step': 0.1})

heli.addBreedParam('rbd', 'Demand for Real Balances', 'slider', dflt={'hobbit':7, 'dwarf': 35}, opts={'low':1, 'high': 50, 'step': 1}, prim='agent', callback=rbalUpdater)
heli.addBreedParam('liqPref', 'Demand for Liquidity', 'slider', dflt={'hobbit': 0.1, 'dwarf': 0.3}, opts={'low':0, 'high': 1, 'step': 0.01}, prim='agent', callback=rbalUpdater, desc='The proportion of the agent\'s balances he desires to keep in cash')

heli.addGoodParam('prod', 'Productivity', 'slider', dflt=1.75, opts={'low':0.1, 'high': 2, 'step': 0.1}) #If you shock productivity, make sure to call rbalupdater

#Takes as input the slider value, outputs b_g. See equation (A8) in the paper.
def rbaltodemand(breed):
	def reporter(model):
		rbd = model.breedParam('rbd', breed, prim='agent')
		beta = rbd/(1+rbd)
		
		return (beta/(1-beta)) * len(model.goods) * sqrt(model.goodParam('prod',AgentGoods[breed])) / sum([1/sqrt(pr) for pr in model.goodParam('prod').values()])

	return reporter

#Data Collection
heli.addPlot('shortage', 'Shortages', 3)
heli.addPlot('rbal', 'Real Balances', 5)
heli.addPlot('capital', 'Production', 9)
heli.addPlot('wage', 'Wage', 11)
heli.addPlot('debt', 'Debt')
heli.addPlot('rr', 'Reserve Ratio')
heli.addPlot('i', 'Interest Rate')

heli.addSeries('capital', lambda: 1/len(heli.primitives['agent']['breeds']), '', 'CCCCCC')
for breed, d in heli.primitives['agent']['breeds'].items():
	heli.data.addReporter('rbalDemand-'+breed, rbaltodemand(breed))
	heli.data.addReporter('eCons-'+breed, heli.data.agentReporter('expCons', 'agent', breed=breed, stat='sum'))
	# heli.data.addReporter('rWage-'+breed, lambda model: heli.data.agentReporter('wage', 'store')(model) / heli.data.agentReporter('price', 'store', good=b.good)(model))
	# heli.data.addReporter('expWage', heli.data.agentReporter('expWage', 'agent'))
	heli.data.addReporter('rBal-'+breed, heli.data.agentReporter('realBalances', 'agent', breed=breed))
	heli.data.addReporter('invTarget-'+AgentGoods[breed], heli.data.agentReporter('invTarget', 'store', good=AgentGoods[breed]))
	heli.data.addReporter('portion-'+AgentGoods[breed], heli.data.agentReporter('portion', 'store', good=AgentGoods[breed]))
	
	heli.addSeries('demand', 'eCons-'+breed, breed.title()+'s\' Expected Consumption', d.color2)
	heli.addSeries('rbal', 'rbalDemand-'+breed, breed.title()+' Target Balances', d.color2)
	heli.addSeries('rbal', 'rBal-'+breed, breed.title()+ 'Real Balances', d.color)
	heli.addSeries('inventory', 'invTarget-'+AgentGoods[breed], AgentGoods[breed].title()+' Inventory Target', heli.goods[AgentGoods[breed]].color2)
	heli.addSeries('capital', 'portion-'+AgentGoods[breed], AgentGoods[breed].title()+' Capital', heli.goods[AgentGoods[breed]].color)
	# heli.addSeries('Wage', 'expWage', 'Expected Wage', '999999')

#Price ratio plots
def ratioReporter(item1, item2):
	def reporter(model):
		return model.data.agentReporter('price', 'store', good=item1)(model)/model.data.agentReporter('price', 'store', good=item2)(model)
	return reporter
heli.addPlot('ratios', 'Price Ratios', position=3, logscale=True)
heli.addSeries('ratios', lambda: 1, '', 'CCCCCC')	#plots ratio of 1 for reference without recording a column of ones

goods = list(heli.goods.keys())
goods.remove(heli.moneyGood)
for r in combinations(goods, 2):
	heli.data.addReporter('ratio-'+r[0]+'-'+r[1], ratioReporter(r[0], r[1]))
	c1, c2 = heli.goods[r[0]].color, heli.goods[r[1]].color
	c3 = Color(red=(c1.red+c2.red)/2, green=(c1.green+c2.green)/2, blue=(c1.blue+c2.blue)/2)
	heli.addSeries('ratios', 'ratio-'+r[0]+'-'+r[1], r[0].title()+'/'+r[1].title()+' Ratio', c3)
heli.defaultPlots.extend(['rbal', 'ratios'])

heli.data.addReporter('storeCash', heli.data.agentReporter('balance', 'store'))
heli.addSeries('money', 'storeCash', 'Store Cash', '777777')
heli.data.addReporter('StoreCashDemand', heli.data.agentReporter('cashDemand', 'store'))
heli.addSeries('money', 'StoreCashDemand', 'Store Cash Demand', 'CCCCCC')
heli.data.addReporter('wage', heli.data.agentReporter('wage', 'store'))
heli.addSeries('wage', 'wage', 'Wage', '000000')

#================
# AGENT BEHAVIOR
#================

#
# General
#

#Don't bother keeping track of the bank-specific variables unless the banking system is there
#Do this here rather than at the beginning so we can decide at runtime
def modelPreSetup(model):
	if model.param('agents_bank') > 0:
		model.data.addReporter('defaults', model.data.agentReporter('defaultTotal', 'bank'))
		model.data.addReporter('debt', model.data.agentReporter('loans', 'bank'))
		model.data.addReporter('reserveRatio', model.data.agentReporter('reserveRatio', 'bank'))
		model.data.addReporter('targetRR', model.data.agentReporter('targetRR', 'bank'))
		model.data.addReporter('i', model.data.agentReporter('i', 'bank'))
		model.data.addReporter('r', model.data.agentReporter('realInterest', 'bank'))
		model.data.addReporter('inflation', model.data.agentReporter('inflation', 'bank'))
		model.data.addReporter('withdrawals', model.data.agentReporter('lastWithdrawal', 'bank'))
		model.data.addReporter('M2', model.data.cbReporter('M2'))

		model.addSeries('money', 'defaults', 'Defaults', 'CC0000')
		model.addSeries('money', 'M2', 'Money Supply', '000000')
		model.addSeries('debt', 'debt', 'Outstanding Debt', '000000')
		model.addSeries('rr', 'targetRR', 'Target', '777777')
		model.addSeries('rr', 'reserveRatio', 'Reserve Ratio', '000000')
		model.addSeries('i', 'i', 'Nominal interest', '000000')
		model.addSeries('i', 'r', 'Real interest', '0000CC')
		model.addSeries('i', 'inflation', 'Inflation', 'CC0000')
heli.addHook('modelPreSetup', modelPreSetup)

#
# Agents
#

from utility import CES

#Choose a bank if necessary
def moneyUserInit(agent, model):
	if model.param('agents_bank') > 0:
		agent.bank = model.agents['bank'][0]
		agent.bank.setupAccount(agent)
heli.addHook('moneyUserInit', moneyUserInit)

def agentInit(agent, model):
	agent.store = model.agents['store'][0]
	agent.item = AgentGoods[agent.breed]
	rbd = model.breedParam('rbd', agent.breed, prim='agent')
	beta = rbd/(rbd+1)
	agent.utility = CES(['good','rbal'], agent.model.param('sigma'), {'good': 1-beta, 'rbal': beta })
	
	#Set cash endowment to equilibrium value based on parameters. Not strictly necessary but avoids the burn-in period.
	agent.goods[model.moneyGood] = agent.store.price[agent.item] * rbaltodemand(agent.breed)(heli)
	
	if model.param('agents_bank') > 0:
		agent.liqPref = model.breedParam('liqPref', agent.breed, prim='agent')
	
	agent.prevBal = agent.balance
	agent.expCons = model.goodParam('prod', agent.item)
	
heli.addHook('agentInit', agentInit)

def agentStep(agent, model, stage):
	itemPrice = agent.store.price[agent.item]
	
	b = agent.balance/itemPrice		#Real balances
	q = agent.utility.demand(agent.balance, {'good': itemPrice, 'rbal': itemPrice})['good']	#Equimarginal condition given CES between real balances and consumption
	basicq = q						#Save this for later since we adjust q
	
	bought = agent.buy(agent.store, agent.item, q, itemPrice)
	if agent.goods[model.moneyGood] < 0: agent.goods[model.moneyGood] = 0	#Floating point error gives infinitessimaly negative cash sometimes
	agent.utils = agent.utility.calculate({'good': agent.goods[agent.item], 'rbal': agent.balance/itemPrice}) if hasattr(agent,'utility') else 0	#Get utility
	agent.goods[agent.item] = 0 #Consume goods
	
	negadjust = q - bought											#Update your consumption expectations if the store has a shortage
	if negadjust > basicq: negadjust = basicq
	agent.expCons = (19 * agent.expCons + basicq-negadjust)/20		#Set expected consumption as a decaying average of consumption history
	
	#Deposit cash in the bank at the end of each period
	if hasattr(agent, 'bank'):
		tCash = agent.liqPref*agent.balance
		agent.bank.deposit(agent, agent.goods[agent.model.moneyGood]-tCash)
heli.addHook('agentStep', agentStep)

def realBalances(agent):
	if not hasattr(agent, 'store'): return 0
	return agent.balance/agent.store.price[agent.item]
	# return agent.balance/agent.model.cb.P
Agent.realBalances = property(realBalances)

#Use the bank if the bank exists
def buy(agent, partner, good, q, p):
	if hasattr(agent, 'bank'):
		bal = agent.bank.balance(agent)
		if p*q > bal:
			amount = bal
			leftover = (p*q - bal)/q
		else:
			amount = p*q
			leftover = 0
		agent.bank.transfer(agent, partner, amount)	
		return (q, leftover)
heli.addHook('buy', buy)

#Use the bank if the bank exists
def pay(agent, recipient, amount, model):
	if hasattr(agent, 'bank'):
		bal = agent.bank.balance(agent)
		# origamt = amount
		if amount > bal: #If there are not enough funds
			trans = bal
			amount -= bal
		else:
			trans = amount
			amount = 0
		agent.bank.transfer(agent, recipient, trans)
		return amount #Should be zero. Anything leftover gets paid in cash
heli.addHook('pay', pay)

def checkBalance(agent, balance, model):
	if hasattr(agent, 'bank'):
		balance += agent.bank.balance(agent)
		return balance
heli.addHook('checkBalance', checkBalance)

#
# Store
#

def storeInit(store, model):
	store.invTarget = {}		#Inventory targets in terms of absolute quantity
	store.portion = {}			#Allocation of capital to the various goods
	store.wage = 0
	store.cashDemand = 0
	
	sm=0
	for g in model.goods:
		if g==model.moneyGood: continue
		sm += 1/sqrt(model.goodParam('prod',g))
		
	for good in model.goods:
		if good==model.moneyGood: continue
		store.portion[good] = 1/(len(model.goods)-1)
		store.invTarget[good] = 1
		
		#Start with equilibrium prices. Not strictly necessary, but it eliminates the burn-in period.
		store.price[good] = M0/model.param('agents_agent') * sm/(sqrt(model.goodParam('prod',good))*(len(model.goods)-1+sum([1+model.breedParam('rbd', b, prim='agent') for b in model.primitives['agent']['breeds']])))
	
	if hasattr(store, 'bank'):
		store.pavg = 0
		store.projects = []
		store.defaults = 0
heli.addHook('storeInit', storeInit)

def storeStep(store, model, stage):
	N = model.param('agents_agent')
		
	#Calculate wages
	store.cashDemand = N * store.wage #Hold enough cash for one period's disbursements
	newwage = (store.balance - store.cashDemand) / N
	if newwage < 1: newwage = 1
	store.wage = (store.wage * model.param('wStick') + newwage)/(1 + model.param('wStick'))
	if store.wage * N > store.balance: store.wage = store.balance / N 	#Budget constraint
	
	#Hire labor
	labor, tPrice = 0, 0
	for a in model.agents['agent']:
		#Pay agents / wage shocks
		if store.wage < 0: store.wage = 0
		wage = random.normal(store.wage, store.wage/2 + 0.1)	#Can't have zero stdev
		wage = 0 if wage < 0 else wage							#Wage bounded from below by 0
		store.pay(a, wage)
		labor += 1
				
	for good in model.goods:
		if good == model.moneyGood: continue
		tPrice += store.price[good] #Sum of prices. This is a separate loop because we need it in order to do this calculation
	
	avg, stdev = {},{} #Hang onto these for use with credit calculations
	for i in model.goods:
		if i == model.moneyGood: continue

		#Keep track of typical demand
		#Target sufficient inventory to handle 1.5 standard deviations above mean demand for the last 50 periods
		history = pandas.Series(model.data.getLast('demand-'+i, 50)) + pandas.Series(model.data.getLast('shortage-'+i, 50))
		avg[i], stdev[i] = history.mean(), history.std()
		itt = (1 if isnan(avg[i]) else avg[i]) + 1.5 * (1 if isnan(stdev[i]) else stdev[i])
		store.invTarget[i] = (store.invTarget[i] + itt)/2 #Smooth it a bit
		
		#Set prices
		#Change in the direction of hitting the inventory target
		# store.price[i] += log(store.invTarget[i] / (store.inventory[i][0] + store.lastShortage[i])) #Jim's pricing rule?
		store.price[i] += (store.invTarget[i] - store.goods[i] + model.data.getLast('shortage-'+i))/100 #/150
		
		#Adjust in proportion to the rate of inventory change
		#Positive deltaInv indicates falling inventory; negative deltaInv rising inventory
		lasti = model.data.getLast('inv-'+i,2)[0] if model.t > 1 else 0
		deltaInv = lasti - store.goods[i]
		store.price[i] *= (1 + deltaInv/(50 ** model.param('pSmooth')))
		if store.price[i] < 0: store.price[i] = 1
		
		#Produce stuff
		store.portion[i] = (model.param('kImmob') * store.portion[i] + store.price[i]/tPrice) / (model.param('kImmob') + 1)	#Calculate capital allocation
		store.goods[i] = store.goods[i] + store.portion[i] * labor * model.goodParam('prod',i)
	
	#Intertemporal transactions
	if hasattr(store, 'bank') and model.t > 0:
		#Stipulate some demand for credit, we can worry about microfoundations later
		store.bank.amortize(store, store.bank.credit[store.unique_id].owe/1.5)
		store.bank.borrow(store, store.model.cb.ngdp * (1-store.bank.i))
			
heli.addHook('storeStep', storeStep)

#
# Central Bank
#

def cbInit(cb, model):
	cb.ngdpTarget = False if not model.param('ngdpTarget') else 10000
heli.addHook('cbInit', cbInit)

def cbStep(cb, model, stage):
	#Set macroeconomic targets at the end of the last stage
	if stage == model.stages:
		expand = 0
		if cb.inflation: expand = M0(model) * cb.inflation
		if cb.ngdpTarget: expand = cb.ngdpTarget - cb.ngdpAvg
		if model.param('agents_bank') > 0: expand *= model.agents['bank'][0].reserveRatio
		if expand != 0: cb.expand(expand)
heli.addHook('cbStep', cbStep)

#========
# SHOCKS
#========

#Random shock to dwarf cash demand
def shock(v):
	c = random.normal(v, 4)
	return c if c >= 1 else 1
heli.shocks.register('Dwarf real balances', 'rbd', shock, heli.shocks.randn(2), paramType='breed', obj='dwarf', prim='agent')

#Shock the money supply
def mshock(model):
	# return v*2
	pct = random.normal(1, 15)
	m = model.cb.M0 * (1+pct/100)
	if m < 10000: m = 10000		#Things get weird when there's a money shortage
	model.cb.M0 = m
heli.shocks.register('M0 (2% prob)', None, mshock, heli.shocks.randn(2), desc="Shocks the money supply a random percentage (µ=1, σ=15) with 2% probability each period")
# heli.registerShock('M0 (every 700 periods)', 'M0', mshock, shock_everyn(700))

heli.launchGUI()
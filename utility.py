# ==========
# Utility functions
# Do not run this file; import model.py and run your file.
# ==========

from abc import ABC, abstractmethod

#Basic utility functions
class Utility():
	
	#Receives an array of goods.
	#Can, but doesn't necessarily have to correspond to the registered goods
	#i.e. you can have an abstract good like real balances
	def __init__(self, goodslist):
		self.goods = goodslist
		self.utils = 0
		
	def consume(self, quantities):
		self.utility = self.calculate(quantities)
		return self.utility

	#Receives an array of quantities
	#Returns a scalar utility
	@abstractmethod
	def calculate(self, quantities):
		pass
	
	#Receives a budget and an array of prices
	#Returns an array of utility-maximizing quantities
	@abstractmethod
	def demand(self, budget, prices):
		pass

#Constant elasticity of substitution
class CES(Utility):
	
	#Coefficients should add to 1, but this is not enforced
	#Coeffs should be a dict with the keys corresponding to the items of goodslist
	def __init__(self, goodslist, elast, coeffs=None):
		super().__init__(goodslist)
		self.elast = elast
		self.coeffs = {g:1 for g in goodslist} if coeffs is None else coeffs
	
	def calculate(self, quantities):
		#Can't divide by zero in the inner exponent
		#But at σ=0, the utility function becomes a Leontief function in the limit
		#The coefficients don't show up, see https://www.jstor.org/stable/29793581
		if self.elast==0: return min(quantities.values())
		
		#Can't divide by zero in the outer exponent
		#But at σ=1, the utility function becomes a Cobb-Douglass function
		#See https://yiqianlu.files.wordpress.com/2013/10/ces-functions-and-dixit-stiglitz-formulation.pdf
		elif self.elast==1:
			util = 1
			for g in self.goods:
				util *= quantities[g] ** self.coeffs[g]
			return util
		
		#Can't raise zero to a negative exponent
		#But as x approaches zero, x^-y approaches infinity
		#So an infinite inner sum means the whole expression becomes zero
		elif (0 in quantities.values()) and self.elast<1: return 0
		
		#The general utility function
		else:
			util = 0
			for g in self.goods:
				util += self.coeffs[g] ** (1/self.elast) * quantities[g] ** ((self.elast-1)/self.elast)
			return util ** (self.elast/(self.elast-1))
	
	def demand(self, budget, prices):
		demand = {g:0 for g in self.goods}
		for g in self.goods:
			# Derivation at https://cameronharwick.com/blog/how-to-derive-a-demand-function-from-a-ces-utility-function/
			for h, price in prices.items():
				demand[g] += self.coeffs[h]/self.coeffs[g] * price ** (1-self.elast)
			demand[g] = budget * prices[g] ** (-self.elast) / demand[g]
			
		return demand

class CobbDouglas(CES):
	def __init__(self, goodslist, exponents=None):
		if exponents is None: exponents = {g: 1/len(goodslist) for g in goodslist}
		super().__init__(goodslist, 1, exponents)

class Leontief(CES):
	def __init__(self, goodslist):
		super().__init__(goodslist, 0)
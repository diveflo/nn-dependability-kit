from . import dataflow
from . import octagon
from ..basic import pytorchreader
from ..basic import neuralnet

import numpy as np
import math
import torch
import torch.nn as nn

from multiprocessing import Pool

def verify(inputMinBound, inputMaxBound, net, isUsingBox = True, inputConstraints = [], riskProperty = [], isAvoidQuadraticConstraints = False, bigM = 1000000.0, numberOfProcesses = 4):

    if isinstance(net, nn.Module):
        # Translate from Pytorch to internal format
        net = pytorchreader.loadMlpFromPytorch(net)
    
    minBound = dict()
    maxBound = dict()

    minBound[0] = inputMinBound
    maxBound[0] = inputMaxBound
    
    with Pool(processes=numberOfProcesses) as pool:
        for layerIndex in range(1, len(net.layers)+1):
            print("[Boxed abstraction] Processing layer "+str(layerIndex))
            # in neuralnet.py for storing weights, the index starts with 0
            weights = net.layers[layerIndex-1]["weights"]
            bias = net.layers[layerIndex-1]["bias"]
        
            numberOfOutputs = weights.shape[0]
            numberOfInputs = weights.shape[1]

            minBound[layerIndex] = np.zeros(numberOfOutputs)
            maxBound[layerIndex] = np.zeros(numberOfOutputs)
        
            if layerIndex == 1:
                # Input layer
                for i in range(numberOfOutputs):
                    
                    min = pool.apply_async(dataflow.deriveReLuOutputBound, (False, layerIndex, weights[i], bias[i], numberOfInputs, i, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], inputConstraints))
                    max = pool.apply_async(dataflow.deriveReLuOutputBound, (True, layerIndex, weights[i], bias[i], numberOfInputs, i, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], inputConstraints)        )
                    minBound[layerIndex][i] = min.get()
                    maxBound[layerIndex][i] = max.get()
                    #minBound[layerIndex][i] = dataflow.deriveReLuOutputBound(False, layerIndex, weights[i], bias[i], numberOfInputs, i, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], inputConstraints)
                    #maxBound[layerIndex][i] = dataflow.deriveReLuOutputBound(True, layerIndex, weights[i], bias[i], numberOfInputs, i, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], inputConstraints)        

            elif layerIndex == len(net.layers):
                # Output layer
                if len(riskProperty) == 0:
                    # Compute output bounds
                    for i in range(numberOfOutputs):
                        min = pool.apply_async(dataflow.deriveLinearOutputBound, (False, layerIndex, weights[i], bias[i], numberOfInputs, i, minBound[layerIndex -1], maxBound[layerIndex -1]))
                        max = pool.apply_async(dataflow.deriveLinearOutputBound, (True, layerIndex, weights[i], bias[i], numberOfInputs, i, minBound[layerIndex -1], maxBound[layerIndex -1]))
                        minBound[layerIndex][i] = min.get()
                        maxBound[layerIndex][i] = max.get()        
                        #minBound[layerIndex][i] = dataflow.deriveLinearOutputBound(False, layerIndex, weights[i], bias[i], numberOfInputs, i, minBound[layerIndex -1], maxBound[layerIndex -1])
                        #maxBound[layerIndex][i] = dataflow.deriveLinearOutputBound(True, layerIndex, weights[i], bias[i], numberOfInputs, i, minBound[layerIndex -1], maxBound[layerIndex -1])        

                else:
                    # Check if the property can be violated
                    isRiskReachable = dataflow.isRiskPropertyReachable(layerIndex, weights, bias, numberOfInputs, numberOfOutputs, minBound[layerIndex -1], maxBound[layerIndex -1], [], riskProperty)        
                    if(isRiskReachable == False):
                        print("Risk property is not reachable (using boxed abstraction)")
                        return [], []
                    else:  
                        print("Risk property may be reachable (using boxed abstraction)")
                    # raise Exception("Currently property are not supported")
            else:
                # Intermediate layer
                for i in range(numberOfOutputs):
                    min = pool.apply_async(dataflow.deriveReLuOutputBound, (False, layerIndex, weights[i], bias[i], numberOfInputs, i, bigM, minBound[layerIndex -1], maxBound[layerIndex -1]))
                    max = pool.apply_async(dataflow.deriveReLuOutputBound, (True, layerIndex, weights[i], bias[i], numberOfInputs, i, bigM, minBound[layerIndex -1], maxBound[layerIndex -1]))
                    minBound[layerIndex][i] = min.get()
                    maxBound[layerIndex][i] = max.get() 
                    #minBound[layerIndex][i] = dataflow.deriveReLuOutputBound(False, layerIndex, weights[i], bias[i], numberOfInputs, i, bigM, minBound[layerIndex -1], maxBound[layerIndex -1])
                    #maxBound[layerIndex][i] = dataflow.deriveReLuOutputBound(True, layerIndex, weights[i], bias[i], numberOfInputs, i, bigM, minBound[layerIndex -1], maxBound[layerIndex -1])        

        if(isUsingBox):
            print("Completed\n\n")
            return minBound[len(net.layers)], maxBound[len(net.layers)]
        

        # Also compute separately to derive the lower bound of the linear sum, in order to get a small bigM value
        minLinearBound = dict()
        minLinearBound[0] = inputMinBound

        for layerIndex in range(1, len(net.layers)+1):
            # in neuralnet.py for storing weights, the index starts with 0
            weights = net.layers[layerIndex-1]["weights"]
            bias = net.layers[layerIndex-1]["bias"]
        
            numberOfOutputs = weights.shape[0]
            numberOfInputs = weights.shape[1]
            minLinearBound[layerIndex] = np.zeros(numberOfOutputs)
            for i in range(numberOfOutputs):
                minLinearBound[layerIndex][i] = dataflow.deriveLinearOutputBound(False, layerIndex, weights[i], bias[i], numberOfInputs, i, minBound[layerIndex -1], maxBound[layerIndex -1])

        # Compute a smaller bigM value, in order to be fed into the Octagon analysis 
        bigM = 0
        for i in range(len(maxBound)):
            if bigM < np.max(np.absolute(maxBound[i])):
                bigM =  np.max(np.absolute(maxBound[i]))
        print("bigM under abs(max bound): "+ str(bigM))
        
        for i in range(len(minLinearBound)):
            if bigM < np.max(np.absolute(minLinearBound[i])):
                bigM =  np.max(np.absolute(minLinearBound[i]))
        print("bigM under abs(min bound): "+ str(bigM))
                
        if bigM == math.inf:
            # Just replace it by some big number (warning - this is a temporarily solution as there are bugs inside cbc LP solver)
            bigM = 30000000
               
        # The user requested to perform analysis over the network with Octagon abstraction
        octagonBound = dict()
        octagonBound[0] = []
        firstLayer = True
        
        for layerIndex in range(1, len(net.layers)+1):

            # in neuralnet.py for storing weights, the index starts with 0
            weights = net.layers[layerIndex-1]["weights"]
            bias = net.layers[layerIndex-1]["bias"]
        
            numberOfOutputs = weights.shape[0]
            numberOfInputs = weights.shape[1]

            octagonBound[layerIndex] = []

            if layerIndex != len(net.layers): 
                print("[Octagon abstraction] Processing layer "+str(layerIndex))
                # Process first & intermediate layer
                inputConstraintForThisLayer = []
                if layerIndex == 1:
                    # For the first layer, the input constraint is taken from parameters
                    inputConstraintForThisLayer = inputConstraints
                    
                if isAvoidQuadraticConstraints == False:
                    for i in range(numberOfOutputs):
                        print("\t["+str(i)+"]: ", end='')
                        for j in range(numberOfOutputs):
                            if (j>i):
                                if(j%5==0):
                                    print(str(j)+"," , end='')
                                
                                min1 = pool.apply_async(octagon.deriveReLuOutputOctagonBound, (False, layerIndex, weights, bias, numberOfInputs, i, j, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], True, inputConstraintForThisLayer))
                                max1 = pool.apply_async(octagon.deriveReLuOutputOctagonBound, (True, layerIndex, weights, bias, numberOfInputs, i, j, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], True, inputConstraintForThisLayer))                                
                                minimumValue1 = min1.get()
                                maximumValue1 = max2.get()                                 
                                #minimumValue1 = octagon.deriveReLuOutputOctagonBound(False, layerIndex, weights, bias, numberOfInputs, i, j, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], True, inputConstraintForThisLayer)
                                #maximumValue2 = octagon.deriveReLuOutputOctagonBound(True, layerIndex, weights, bias, numberOfInputs, i, j, bigM,  minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], True, inputConstraintForThisLayer)        
                                min2 = pool.apply_async(octagon.deriveReLuOutputOctagonBound, (False, layerIndex, weights, bias, numberOfInputs, i, j, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], False, inputConstraintForThisLayer))
                                max2 = pool.apply_async(octagon.deriveReLuOutputOctagonBound, (True, layerIndex, weights, bias, numberOfInputs, i, j, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], False, inputConstraintForThisLayer))                                
                                minimumValue2 = min2.get()
                                maximumValue2 = max2.get()                                 
                                #minimumValue = octagon.deriveReLuOutputOctagonBound(False, layerIndex, weights, bias, numberOfInputs, i, j, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], False, inputConstraintForThisLayer)
                                #maximumValue = octagon.deriveReLuOutputOctagonBound(True, layerIndex, weights, bias, numberOfInputs, i, j, bigM,  minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], False, inputConstraintForThisLayer)                                        
                                
                                vari = "v_"+str(layerIndex)+"_"+str(i)
                                varj = "v_"+str(layerIndex)+"_"+str(j)
                                # v_i - v_j
                                octagonconstraint1 = [minimumValue1, vari, -1, varj, maximumValue1]
                                octagonBound[layerIndex].append(octagonconstraint1)
                                # v_i + v_j
                                octagonconstraint2 = [minimumValue2, vari, 1, varj, maximumValue2]
                                octagonBound[layerIndex].append(octagonconstraint2)
                                                                
                                
                        print()                
                else:
                    # Only create octagon difference constraints linear to the size of the neuron
                    # (i, i+1)
                    print("  (constraint shape x_{i} - x_{i+1}: ", end='\n')
                    print("  (constraint shape x_{i} + x_{i+1}: ", end='')
                    for i in (range(numberOfOutputs  -1)):  
                        if(i%5==0):
                            print(str(i)+"," , end='')
                        octagonconstraint = []
                        min1 = pool.apply_async(octagon.deriveReLuOutputOctagonBound, (False, layerIndex, weights, bias, numberOfInputs, i, i+1, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], True, inputConstraintForThisLayer))
                        max1 = pool.apply_async(octagon.deriveReLuOutputOctagonBound, (True, layerIndex, weights, bias, numberOfInputs, i, i+1, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], True, inputConstraintForThisLayer))                              
                        minimumValue1 = min1.get()
                        maximumValue1 = max1.get() 
                        #minimumValue = octagon.deriveReLuOutputOctagonBound(False, layerIndex, weights, bias, numberOfInputs, i, i+1, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], True, inputConstraintForThisLayer)
                        #maximumValue = octagon.deriveReLuOutputOctagonBound(True, layerIndex, weights, bias, numberOfInputs, i, i+1, bigM,  minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], True, inputConstraintForThisLayer)        


                        min2 = pool.apply_async(octagon.deriveReLuOutputOctagonBound, (False, layerIndex, weights, bias, numberOfInputs, i, i+1, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], False, inputConstraintForThisLayer))
                        max2 = pool.apply_async(octagon.deriveReLuOutputOctagonBound, (True, layerIndex, weights, bias, numberOfInputs, i, i+1, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], False, inputConstraintForThisLayer))
                        minimumValue2 = min2.get()
                        maximumValue2 = max2.get() 
                        #minimumValue = octagon.deriveReLuOutputOctagonBound(False, layerIndex, weights, bias, numberOfInputs, i, i+1, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], False, inputConstraintForThisLayer)
                        #maximumValue = octagon.deriveReLuOutputOctagonBound(True, layerIndex, weights, bias, numberOfInputs, i, i+1, bigM,  minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], False, inputConstraintForThisLayer)                                
                        vari = "v_"+str(layerIndex)+"_"+str(i)
                        varj = "v_"+str(layerIndex)+"_"+str(i+1)
                        
                        # v_i - v_j
                        octagonconstraint1 = [minimumValue1, vari, -1, varj, maximumValue1]
                        octagonBound[layerIndex].append(octagonconstraint1)
                        # v_i + v_j
                        octagonconstraint2 = [minimumValue2, vari, 1, varj, maximumValue2]
                        octagonBound[layerIndex].append(octagonconstraint2)    
                        
                    print()                      
                    # (i, i+ N/2)  
                    print("  (constraint shape x_{i} - x_{i+(N/2)}: ", end='\n')
                    print("  (constraint shape x_{i} + x_{i+(N/2)}: ", end='')                      
                    half = (int(math.ceil(numberOfOutputs)/2))
                    for i in range(half):   
                        if(i%5==0):
                            print(str(i)+"," , end='')                     
                        
                        min1 = pool.apply_async(octagon.deriveReLuOutputOctagonBound, (False, layerIndex, weights, bias, numberOfInputs, i, i+half, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], True, inputConstraintForThisLayer))
                        max1 = pool.apply_async(octagon.deriveReLuOutputOctagonBound, (True, layerIndex, weights, bias, numberOfInputs, i, i+half, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], True, inputConstraintForThisLayer))
                        minimumValue1 = min1.get()
                        maximumValue1 = max1.get() 
                        
                        #minimumValue = octagon.deriveReLuOutputOctagonBound(False, layerIndex, weights, bias, numberOfInputs, i, i+half, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], True, inputConstraintForThisLayer)
                        #maximumValue = octagon.deriveReLuOutputOctagonBound(True, layerIndex, weights, bias, numberOfInputs, i, i+half, bigM,  minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], True, inputConstraintForThisLayer)        

                        min2 = pool.apply_async(octagon.deriveReLuOutputOctagonBound, (False, layerIndex, weights, bias, numberOfInputs, i, i+half, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], False, inputConstraintForThisLayer))
                        max2 = pool.apply_async(octagon.deriveReLuOutputOctagonBound, (True, layerIndex, weights, bias, numberOfInputs, i, i+half, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], False, inputConstraintForThisLayer))
                        minimumValue2 = min2.get()
                        maximumValue2 = max2.get()
                        #minimumValue = octagon.deriveReLuOutputOctagonBound(False, layerIndex, weights, bias, numberOfInputs, i, i+half, bigM, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], False, inputConstraintForThisLayer)
                        #maximumValue = octagon.deriveReLuOutputOctagonBound(True, layerIndex, weights, bias, numberOfInputs, i, i+half, bigM,  minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], False, inputConstraintForThisLayer)        
                        
                        vari = "v_"+str(layerIndex)+"_"+str(i)
                        varj = "v_"+str(layerIndex)+"_"+str(i+half)
                        
                        octagonconstraint1 = [minimumValue1, vari, -1, varj, maximumValue1]
                        octagonBound[layerIndex].append(octagonconstraint1)
                        octagonconstraint2 = [minimumValue2, vari, 1, varj, maximumValue2]
                        octagonBound[layerIndex].append(octagonconstraint2)                        
                    print()                          
                print("Layer "+str(layerIndex) +": completed")
            print()


        for layerIndex in range(1, len(net.layers)+1):
            if(layerIndex == len(net.layers)):
                print("[Octagon abstraction] Processing layer "+str(layerIndex))
                weights = net.layers[layerIndex-1]["weights"]
                bias = net.layers[layerIndex-1]["bias"]
            
                numberOfOutputs = weights.shape[0]
                numberOfInputs = weights.shape[1]
                

                minBoundOctagon = np.zeros(numberOfOutputs)
                maxBoundOctagon = np.zeros(numberOfOutputs)
                

                if len(riskProperty) == 0:
                    # Perform bound analysis over the final layer. 
                    for i in range(numberOfOutputs):
                        print (str(layerIndex) + "  "+str(i))
                        min = pool.apply_async(dataflow.deriveLinearOutputBound, (False, layerIndex, weights[i], bias[i], numberOfInputs, i, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1]))
                        max = pool.apply_async(dataflow.deriveLinearOutputBound, (True, layerIndex, weights[i], bias[i], numberOfInputs, i, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1]))
                        minBoundOctagon[i] = min.get()
                        maxBoundOctagon[i] = max.get()
                        
                        #minBoundOctagon[i] = dataflow.deriveLinearOutputBound(False, layerIndex, weights[i], bias[i], numberOfInputs, i, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1])
                        #maxBoundOctagon[i] = dataflow.deriveLinearOutputBound(True, layerIndex, weights[i], bias[i], numberOfInputs, i, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1])        
                    return minBoundOctagon, maxBoundOctagon
                else:
                    # Check if the property can be violated
                    isRiskReachable = dataflow.isRiskPropertyReachable(layerIndex, weights, bias, numberOfInputs, numberOfOutputs, minBound[layerIndex -1], maxBound[layerIndex -1], octagonBound[layerIndex -1], riskProperty)        
                    if(isRiskReachable == False):
                        print("Risk property is not reachable (using octagon abstraction)")
                        return [], []    
                    else:
                        print("Risk property may be reachable (using octagon abstraction)")
                        return [], []                          

                        
                        
    return
    

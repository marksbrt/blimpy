from blimpy import Waterfall
import numpy as np
import pylab as plt
from scipy.integrate import trapz

def foldcal(data,tsamp, diode_p=0.04,numsamps=1000,switch=False,inds=False):
    '''
    Returns time-averaged spectra of the ON and OFF measurements in a
    calibrator measurement with flickering noise diode
    '''

    halfper = diode_p/2.0

    foldt = halfper/tsamp   #number of time samples per diode switch

    onesec = 1/tsamp    #number of time samples in the first second

    #Find diode switches in units of time samples and round down to the nearest int
    ints = np.arange(0,numsamps)
    t_switch = (onesec+ints*foldt)
    t_switch = t_switch.astype('int')

    ONints = np.array(np.reshape(t_switch[:],(numsamps/2,2)))
    ONints[:,0] = ONints[:,0]+1   #Find index ranges of ON time samples

    OFFints = np.array(np.reshape(t_switch[1:-1],(numsamps/2-1,2)))
    OFFints[:,0] = OFFints[:,0]+1   #Find index ranges of OFF time samples

    av_ON = []
    av_OFF = []

    #Average ON and OFF spectra separately with respect to time
    for i in ONints:
        if i[1]!=i[0]:
            av_ON.append(np.sum(data[i[0]:i[1],:,:],axis=0)/(i[1]-i[0]))

    for i in OFFints:
        if i[1]!=i[0]:
            av_OFF.append(np.sum(data[i[0]:i[1],:,:],axis=0)/(i[1]-i[0]))

    if switch==False:
        if inds==False:
            return np.squeeze(np.mean(av_ON,axis=0)), np.squeeze(np.mean(av_OFF,axis=0))
        else:
            return np.squeeze(np.mean(av_ON,axis=0)), np.squeeze(np.mean(av_OFF,axis=0)),ONints,OFFints
    if switch==True:
        if inds==False:
            return np.squeeze(np.mean(av_OFF,axis=0)), np.squeeze(np.mean(av_ON,axis=0))
        else:
            return np.squeeze(np.mean(av_OFF,axis=0)), np.squeeze(np.mean(av_ON,axis=0)),OFFints,ONints

def integrate_chans(spec,freqs,chan_per_core):
    '''Integrates each core channel of a given spectrum'''

    num_cores = spec.size/chan_per_core     #Calculate number of coarse channels

    spec_shaped = np.array(np.reshape(spec,(num_cores,chan_per_core)))
    freqs_shaped = np.array(np.reshape(freqs,(num_cores,chan_per_core)))

    return -1*trapz(spec_shaped,freqs_shaped,axis=1)   #Integrate along core channel axis

def integrate_calib(name,chan_per_core,**kwargs):
    '''Folds noise diode data and integrates along coarse channels'''
    #Load data
    obs = Waterfall(name,max_load=150)
    data = obs.data

    #If the data has cross_pols format calculate Stokes I
    if data.shape[1]>1:
        data = data[:,0,:]+data[:,1,:]
        data = np.expand_dims(data,axis=1)

    tsamp = obs.header['tsamp']

    #Calculate ON and OFF values
    OFF,ON = foldcal(data,tsamp,**kwargs)

    freqs = obs.populate_freqs()

    #Find ON and OFF average spectra
    ON_int = integrate_chans(ON,freqs,chan_per_core)
    OFF_int = integrate_chans(OFF,freqs,chan_per_core)

    #If "ON" is actually "OFF" switch them
    if np.sum(ON_int)<np.sum(OFF_int):
        temp = ON_int
        ON_int = OFF_int
        OFF_int = temp

    return ON_int,OFF_int

def get_calfluxes(calflux,calfreq,spec_in,centerfreqs,oneflux):
    '''
    Given properties of the calibrator source, calculate fluxes of the source
    in a particular frequency range

    Use oneflux to choose between calculating the flux for each core channel (False)
    or using one value for the entire frequency range (True)
    '''

    const = calflux/np.power(calfreq,spec_in)
    if oneflux==False:
        return const*np.power(centerfreqs,spec_in)
    else:
        return const*np.power(np.mean(centerfreqs),spec_in)

def get_centerfreqs(freqs,chan_per_core):
    '''Returns central frequency of each coarse channel'''

    num_cores = freqs.size/chan_per_core
    freqs = np.reshape(freqs,(num_cores,chan_per_core))
    return np.mean(freqs,axis=1)

def diode_spec(ON_obs,OFF_obs,chan_per_core,calflux,calfreq,spec_in,oneflux=True,**kwargs):
    '''Calculate the coarse channel spectrum of the noise diode in Jy'''

    #Calculate noise diode ON and noise diode OFF spectra for both observations
    #ON_OFF -- Noise diode ON, Calibrator OFF etc.
    ON_ON,ON_OFF = integrate_calib(ON_obs,chan_per_core,**kwargs)
    OFF_ON,OFF_OFF = integrate_calib(OFF_obs,chan_per_core,**kwargs)
    obs = Waterfall(ON_obs,max_load=150)
    freqs = obs.populate_freqs()

    #Find difference in counts between observations on the calibrator and off the calibrator
    caldiff1 = ON_ON-OFF_ON
    caldiff2 = ON_OFF-OFF_OFF
    caldiff = (caldiff1+caldiff2)/2

    #Obtain spectrum of the calibrator source for the given frequency range
    centerfreqs = get_centerfreqs(freqs,chan_per_core)
    calfluxes = get_calfluxes(calflux,calfreq,spec_in,centerfreqs,oneflux)

    #Calculate Jy/count factors for each coarse channel
    scalefacs = calfluxes/caldiff

    #Convert all observations to Jy
    ON_ON_scaled = ON_ON*scalefacs
    ON_OFF_scaled = ON_OFF*scalefacs
    OFF_ON_scaled = OFF_ON*scalefacs
    OFF_OFF_scaled = OFF_OFF*scalefacs

    #Find diode spectrum in Jy
    diodiff1 = ON_ON_scaled-ON_OFF_scaled
    diodiff2 = OFF_ON_scaled-OFF_OFF_scaled
    diodiff = (diodiff1+diodiff2)/2
    return diodiff

def calibrate_fluxes(name,dio_name,dspec,dio_chan_per_core,obs_chan_per_core,**kwargs):
    '''
    Produce calibrated Stokes I for an observation given a noise diode
    measurement on the source and a diode spectrum with the same number of
    coarse channels
    '''

    #Find folded spectra of the target source with the noise diode ON and OFF
    obs = Waterfall(name,max_load=150)
    dON,dOFF = integrate_calib(dio_name,dio_chan_per_core,**kwargs)

    #Find Jy/count for each coarse channel using the diode spectrum
    data = obs.data
    scale_facs = dspec/(dON-dOFF)

    nchans = obs.header['nchans']
    ncoarse = nchans/obs_chan_per_core

    ax0_size = np.size(data,0)
    ax1_size = np.size(data,1)

    #Reshape data array of target observation and multiply coarse channels by the scale factors
    data = np.reshape(data,(ax0_size,ax1_size,ncoarse,obs_chan_per_core))
    data = np.swapaxes(data,2,3)

    data = data*scale_facs
    data = np.swapaxes(data,2,3)
    data = np.reshape(data,(ax0_size,ax1_size,nchans))

    #Write calibrated data to a new filterbank file with ".fluxcal" extension
    obs.data = data
    obs.write_to_filterbank(name[:-4]+'.fluxcal.fil')
    print 'Finished: calibrated product written to ' + name[:-4]+'.fluxcal.fil'


#end module

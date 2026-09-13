package com.suhas.ucsentinel.ui
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Radar
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.suhas.ucsentinel.domain.model.ScannerSection

@Composable fun ScannerScreen(state:UiState,vm:MainViewModel,padding:PaddingValues){
    var section by remember{mutableIntStateOf(0)}
    Column(Modifier.fillMaxSize().padding(padding)){
        AppHeader("Live Scanner","Two independent models + all recent NSE listings")
        TabRow(selectedTabIndex=section){Tab(selected=section==0,onClick={section=0},text={Text("Upper Circuit")});Tab(selected=section==1,onClick={section=1},text={Text("Demand/Supply")});Tab(selected=section==2,onClick={section=2},text={Text("New Listings")})}
        LazyColumn(Modifier.fillMaxSize().padding(horizontal=16.dp),verticalArrangement=Arrangement.spacedBy(10.dp),contentPadding=PaddingValues(vertical=12.dp,bottom=24.dp)){
            item{StatusStrip(state)}
            item{Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){OutlinedButton(vm::refreshUniverse,enabled=!state.busy,modifier=Modifier.weight(1f)){Icon(Icons.Default.Refresh,null);Spacer(Modifier.width(5.dp));Text("Refresh master")};Button(vm::runScan,enabled=!state.busy&&state.authenticated,modifier=Modifier.weight(1f)){Icon(Icons.Default.Radar,null);Spacer(Modifier.width(5.dp));Text("Scan all")}}}
            when(section){
                0->{val s=state.dualSummary?.uc; if(s==null)item{EmptyState("UC scanner ready","Looks only for next-session upper-circuit continuation.")}else{item{AccuracyCard(state,ScannerSection.UC_CONTINUATION)};if(s.candidates.isEmpty())item{EmptyState("NO QUALIFIED UC CANDIDATE","No forced recommendation.")}else items(s.candidates){CandidateCard(it)}}}
                1->{val s=state.dualSummary?.demand;if(s==null)item{EmptyState("Demand/Supply scanner ready","Looks for extreme demand with unusually thin visible supply before the stock reaches upper circuit.")}else{item{AccuracyCard(state,ScannerSection.DEMAND_SQUEEZE)};if(s.candidates.isEmpty())item{EmptyState("NO DEMAND-SQUEEZE CANDIDATE","No stock cleared the demand/supply threshold.")}else items(s.candidates){CandidateCard(it)}}}
                else->{item{Button(vm::refreshNewListings,enabled=!state.busy,modifier=Modifier.fillMaxWidth()){Text("Refresh new listings")}}; if(state.newListings.isEmpty())item{EmptyState("No listings loaded","Loads NSE-listed securities from the last ${state.settings.newListingDays} days.")}else items(state.newListings){n->ElevatedCard(Modifier.fillMaxWidth()){Column(Modifier.padding(14.dp)){Text(n.symbol,style=MaterialTheme.typography.titleMedium);Text(n.companyName);Text("Listed ${n.listingDateIso} • ${n.daysListed} days ago",color=MaterialTheme.colorScheme.tertiary);Text("Series ${n.series} • ${n.isin}",color=MaterialTheme.colorScheme.onSurfaceVariant)}}}}
            }
        }
    }
}

@Composable private fun AccuracyCard(state:UiState,section:ScannerSection){val a=state.accuracies[section];ElevatedCard(Modifier.fillMaxWidth()){Row(Modifier.padding(14.dp),horizontalArrangement=Arrangement.spacedBy(18.dp)){Column(Modifier.weight(1f)){Text("Model accuracy",style=MaterialTheme.typography.labelMedium);Text(if(a==null||a.evaluated==0)"Learning" else "%.1f%%".format(a.accuracyPct),style=MaterialTheme.typography.titleLarge)};Column(Modifier.weight(1f)){Text("Last 24h",style=MaterialTheme.typography.labelMedium);Text(if(a==null||a.last24hEvaluated==0)"—" else "%.1f%%".format(a.last24hAccuracyPct),style=MaterialTheme.typography.titleLarge)};Column(Modifier.weight(1f)){Text("Sample",style=MaterialTheme.typography.labelMedium);Text("${a?.hits?:0}/${a?.evaluated?:0}",style=MaterialTheme.typography.titleLarge)}}}}
